"""Embeddings de catalogo para busca semantica, sem incluir dados pessoais."""

from math import isfinite
from typing import Any

import httpx
from pydantic import SecretStr

DIMENSOES = 768
MODELO = "gemini-embedding-2"
URL_EMBEDDING = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{MODELO}:embedContent"
)


class EmbeddingIndisponivel(Exception):
    """A API de embeddings nao concluiu a solicitacao ou retornou dados invalidos."""


def texto_produto(produto: dict[str, Any]) -> str:
    """Monta um documento curto com atributos publicos do catalogo."""
    partes = [
        ("produto", produto.get("nome")),
        ("marca", produto.get("marca")),
        ("categoria", produto.get("categoria")),
        ("colecao", produto.get("colecao")),
        ("tipo", produto.get("tipo")),
        ("cores", produto.get("cores")),
        ("tecido", produto.get("tecido")),
        ("tecelagem", produto.get("tecelagem")),
        ("confeccao", produto.get("costurado_em")),
        ("detalhes", produto.get("nota")),
    ]
    return " | ".join(
        f"{rotulo}: {valor}" for rotulo, valor in partes if valor not in (None, "", [], {})
    )


def gerar(texto: str, chave: SecretStr | str) -> list[float]:
    """Gera vetor Gemini de 768 dimensoes; mensagens/erros nunca incluem a chave."""
    segredo = chave.get_secret_value() if isinstance(chave, SecretStr) else chave
    if not segredo:
        raise EmbeddingIndisponivel("Chave de embedding nao configurada")
    try:
        with httpx.Client(timeout=20) as cliente:
            resposta = cliente.post(
                URL_EMBEDDING,
                headers={"x-goog-api-key": segredo},
                json={
                    "content": {"parts": [{"text": texto}]},
                    "outputDimensionality": DIMENSOES,
                },
            )
            resposta.raise_for_status()
            valores = resposta.json()["embedding"]["values"]
        if (
            not isinstance(valores, list)
            or len(valores) != DIMENSOES
            or any(not isinstance(valor, (int, float)) for valor in valores)
            or any(not isfinite(valor) for valor in valores)
        ):
            raise ValueError("Dimensao de embedding invalida")
        return [float(valor) for valor in valores]
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as erro:
        raise EmbeddingIndisponivel("Servico de embeddings indisponivel") from erro


def serializar(vetor: list[float]) -> str:
    return "[" + ",".join(str(valor) for valor in vetor) + "]"
