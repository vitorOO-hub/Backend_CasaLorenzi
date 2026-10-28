"""Embeddings das pecas para a busca semantica do assistente (Gemini `gemini-embedding-001`).

A coluna `produto.embedding` e `vector(768)` com indice HNSW de cosseno (migration
20261027120000); o modelo devolve 768 dimensoes com `outputDimensionality`. Quem gera os vetores
das pecas e `scripts/gerar_embeddings_produtos.py`; aqui fica a chamada ao Gemini e o texto que
representa cada peca. A chave vai no cabecalho e nao aparece em log nem em erro.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from typing import Any

import httpx
from sqlalchemy import text

from app.core.config import Settings

log = logging.getLogger(__name__)

MODELO = "gemini-embedding-001"
DIMENSOES = 768
URL = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:{acao}"
# A busca do cliente espera pouco: se o Gemini demorar, fica so a busca por palavras.
TEMPO_DA_CONSULTA_SEGUNDOS = 5.0
TEMPO_DO_LOTE_SEGUNDOS = 60.0
TAMANHO_DO_LOTE = 100  # limite do batchEmbedContents

Vetorizar = Callable[[str], list[float]]


class ErroEmbedding(RuntimeError):
    def __init__(self, motivo: str, status: int | None = None) -> None:
        super().__init__(motivo)
        self.status = status


class EmbeddingsGemini:
    def __init__(self, chave: str, cliente: httpx.Client | None = None) -> None:
        self._cabecalhos = {"x-goog-api-key": chave}
        self._cliente = cliente or httpx.Client()

    def _postar(self, acao: str, corpo: dict[str, Any], tempo: float) -> dict[str, Any]:
        try:
            resposta = self._cliente.post(
                URL.format(modelo=MODELO, acao=acao),
                headers=self._cabecalhos,
                json=corpo,
                timeout=tempo,
            )
        except httpx.HTTPError as erro:
            raise ErroEmbedding(f"falha de conexao ({type(erro).__name__})") from erro
        if resposta.is_error:
            raise ErroEmbedding(f"HTTP {resposta.status_code}", resposta.status_code)
        try:
            return resposta.json()
        except ValueError as erro:
            raise ErroEmbedding("resposta ilegivel") from erro

    def consulta(self, texto: str) -> list[float]:
        """Vetor da pergunta do cliente."""
        dados = self._postar(
            "embedContent",
            {
                "content": {"parts": [{"text": texto}]},
                "taskType": "RETRIEVAL_QUERY",
                "outputDimensionality": DIMENSOES,
            },
            TEMPO_DA_CONSULTA_SEGUNDOS,
        )
        return _vetor(dados.get("embedding"))

    def documentos(self, textos: list[str]) -> list[list[float]]:
        """Vetores das pecas, ate TAMANHO_DO_LOTE por chamada."""
        if len(textos) > TAMANHO_DO_LOTE:
            raise ValueError(f"no maximo {TAMANHO_DO_LOTE} textos por lote")
        dados = self._postar(
            "batchEmbedContents",
            {
                "requests": [
                    {
                        "model": f"models/{MODELO}",
                        "content": {"parts": [{"text": texto}]},
                        "taskType": "RETRIEVAL_DOCUMENT",
                        "outputDimensionality": DIMENSOES,
                    }
                    for texto in textos
                ]
            },
            TEMPO_DO_LOTE_SEGUNDOS,
        )
        vetores = [_vetor(e) for e in dados.get("embeddings") or []]
        if len(vetores) != len(textos):
            raise ErroEmbedding("o lote voltou com um numero diferente de vetores")
        return vetores


def _vetor(embedding: Any) -> list[float]:
    valores = embedding.get("values") if isinstance(embedding, dict) else None
    if not isinstance(valores, list) or len(valores) != DIMENSOES:
        raise ErroEmbedding("vetor com tamanho inesperado")
    return [float(v) for v in valores]


def vetorizador(configuracoes: Settings) -> Vetorizar | None:
    """Funcao que vetoriza a pergunta, ou None sem chave do Gemini (busca so por palavras)."""
    chave = configuracoes.gemini_api_key
    if not chave or not chave.get_secret_value().strip():
        return None
    return EmbeddingsGemini(chave.get_secret_value()).consulta


def texto_do_produto(produto: dict[str, Any]) -> str:
    """O que representa a peca na busca: nome, marca, categoria, colecao, tipo, tecido, cores e
    a nota do catalogo (a antiga `descricao` virou `colecao` na migration 20261019120000)."""
    cores = produto.get("cores")
    if isinstance(cores, str):
        try:
            cores = json.loads(cores)
        except ValueError:
            cores = None
    nomes_das_cores = [c.get("nome") for c in cores or [] if isinstance(c, dict) and c.get("nome")]
    partes = [
        produto.get("nome"),
        f"marca {produto['marca']}" if produto.get("marca") else None,
        f"categoria {produto['categoria']}" if produto.get("categoria") else None,
        f"colecao {produto['colecao']}" if produto.get("colecao") else None,
        produto.get("tipo"),
        f"tecido {produto['tecido']}" if produto.get("tecido") else None,
        produto.get("tecelagem"),
        f"cores {', '.join(nomes_das_cores)}" if nomes_das_cores else None,
        produto.get("nota"),
    ]
    return ". ".join(str(p).strip() for p in partes if p and str(p).strip())


def vetor_sql(vetor: list[float]) -> str:
    """Literal aceito por CAST(... AS extensions.vector)."""
    return "[" + ",".join(f"{v:.7f}" for v in vetor) + "]"


# ---------------------------------------------------------------- pecas sem embedding


def pecas_pendentes(conexao: Any, *, todas: bool = False) -> list[dict[str, Any]]:
    """Pecas ativas sem embedding ou editadas depois dele (`atualizado_em > embedding_em`)."""
    filtro = "" if todas else "AND (embedding IS NULL OR embedding_em < atualizado_em)"
    linhas = conexao.execute(
        text(
            f"""
            SELECT id_produto, nome, marca, categoria, colecao, tipo, tecido, tecelagem, cores,
                   nota
            FROM produto
            WHERE ativo {filtro}
            ORDER BY id_produto
            """  # nosec B608 - o filtro e um de dois textos fixos deste modulo
        )
    ).mappings()
    return [dict(linha) for linha in linhas]


def gravar_embeddings(conexao: Any, vetores: list[tuple[Any, list[float]]]) -> None:
    """Grava os vetores e a data; nao mexe em `atualizado_em` (a peca nao foi editada)."""
    for id_produto, vetor in vetores:
        conexao.execute(
            text(
                "UPDATE produto SET embedding = CAST(:vetor AS extensions.vector), "
                "embedding_em = now() WHERE id_produto = :id"
            ),
            {"vetor": vetor_sql(vetor), "id": id_produto},
        )


def gerar(
    conexao: Any,
    gerador: EmbeddingsGemini,
    pecas: list[dict[str, Any]],
    *,
    aplicar: bool,
    tamanho_do_lote: int = TAMANHO_DO_LOTE,
    pausa: float = 0.0,
    dormir: Callable[[float], None] | None = None,
    tentativas: int = 5,
) -> int:
    """Vetoriza em lotes e grava cada lote (com commit) quando `aplicar`. Devolve quantas.

    O plano gratuito do Gemini conta cada peca do lote como uma requisicao: lotes pequenos, uma
    `pausa` entre eles e, no limite (HTTP 429), espera um minuto e tenta de novo.
    """
    dormir = dormir or time.sleep
    feitas = 0
    for inicio in range(0, len(pecas), tamanho_do_lote):
        lote = pecas[inicio : inicio + tamanho_do_lote]
        if inicio and pausa:
            dormir(pausa)
        for tentativa in range(tentativas):
            try:
                vetores = gerador.documentos([texto_do_produto(p) for p in lote])
                break
            except ErroEmbedding as erro:
                if erro.status != 429 or tentativa == tentativas - 1:
                    raise
                log.warning("limite do Gemini; esperando 60 s (tentativa %s)", tentativa + 1)
                dormir(60)
        if aplicar:
            gravar_embeddings(
                conexao, [(p["id_produto"], v) for p, v in zip(lote, vetores, strict=True)]
            )
            conexao.commit()
        feitas += len(lote)
    return feitas
