"""Embeddings das pecas: chamada ao Gemini (HTTP falso), texto da peca e busca na ferramenta."""

import json
from uuid import uuid4

import httpx
import pytest

from app.assistente.cliente import embeddings
from app.assistente.cliente import ferramentas as modulo
from app.assistente.cliente.ferramentas import Ferramentas
from app.core.config import Settings
from app.core.papeis import UsuarioAtual
from tests.conftest import DATABASE_URL_TESTE

CHAVE = "chave-gemini-de-teste"
VETOR = [0.1] * embeddings.DIMENSOES


def _gerador(respostas, pedidos):
    fila = list(respostas)

    def tratar(requisicao):
        pedidos.append(requisicao)
        resposta = fila.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta

    return embeddings.EmbeddingsGemini(CHAVE, httpx.Client(transport=httpx.MockTransport(tratar)))


def test_consulta_pede_768_dimensoes_com_a_chave_so_no_cabecalho():
    pedidos = []
    vetor = _gerador(
        [httpx.Response(200, json={"embedding": {"values": VETOR}})], pedidos
    ).consulta("camisa para casamento")
    assert vetor == VETOR
    (requisicao,) = pedidos
    assert requisicao.headers["x-goog-api-key"] == CHAVE
    assert CHAVE not in str(requisicao.url)
    # Mesmo modelo e mesma chamada do chatbot do admin: os dois usam a coluna produto.embedding.
    assert str(requisicao.url).endswith("/models/gemini-embedding-2:embedContent")
    corpo = json.loads(requisicao.content)
    assert corpo["outputDimensionality"] == 768 and "taskType" not in corpo


def test_documentos_em_lote():
    pedidos = []
    resposta = httpx.Response(200, json={"embeddings": [{"values": VETOR}, {"values": VETOR}]})
    vetores = _gerador([resposta], pedidos).documentos(["a", "b"])
    assert len(vetores) == 2
    corpo = json.loads(pedidos[0].content)
    assert [r["model"] for r in corpo["requests"]] == ["models/gemini-embedding-2"] * 2
    assert all("taskType" not in r for r in corpo["requests"])
    with pytest.raises(ValueError):
        _gerador([], []).documentos(["x"] * (embeddings.TAMANHO_DO_LOTE + 1))


@pytest.mark.parametrize(
    "resposta",
    [
        httpx.Response(500, text=f"erro {CHAVE}"),
        httpx.Response(200, json={"embedding": {"values": [0.1, 0.2]}}),
        httpx.Response(200, text="<html>"),
        httpx.ReadTimeout("lento"),
    ],
)
def test_falhas_viram_erro_de_embedding_sem_a_chave(resposta):
    with pytest.raises(embeddings.ErroEmbedding) as erro:
        _gerador([resposta], []).consulta("x")
    assert CHAVE not in str(erro.value)


def test_vetorizador_so_existe_com_chave_do_gemini(monkeypatch):
    # O conftest desliga o vetorizador; aqui testamos a funcao original.
    monkeypatch.undo()
    base = {"_env_file": None, "database_url": DATABASE_URL_TESTE}
    assert embeddings.vetorizador(Settings(**base)) is None
    assert embeddings.vetorizador(Settings(**base, gemini_api_key="   ")) is None
    assert callable(embeddings.vetorizador(Settings(**base, gemini_api_key="k")))


def test_texto_da_peca_e_o_literal_do_vetor():
    texto = embeddings.texto_do_produto(
        {
            "nome": "Camisa Linho",
            "marca": "Casa Lorenzi",
            "categoria": "camisas",
            "tecido": "linho",
            "colecao": "verao 26",
            "cores": json.dumps([{"nome": "Branco"}, {"nome": "Azul"}]),
            "nota": "Leve, para o calor.",
        }
    )
    assert texto == (
        "Camisa Linho. marca Casa Lorenzi. categoria camisas. colecao verao 26. tecido linho. "
        "cores Branco, Azul. Leve, para o calor."
    )
    assert embeddings.vetor_sql([0.5, -0.25]) == "[0.5000000,-0.2500000]"


# ------------------------------------------------------------------ buscar_produto


def _peca(nome, distancia=None):
    peca = {"nome": nome, "categoria": "c", "marca": "m", "preco_base": 1, "variacoes": []}
    return {**peca, "distancia": distancia} if distancia is not None else peca


def test_busca_junta_palavras_e_semelhanca_sem_repetir(monkeypatch):
    monkeypatch.setattr(
        modulo.repositorio, "buscar_produtos", lambda c, termos, limite: [_peca("Terno La")]
    )
    monkeypatch.setattr(
        modulo.repositorio,
        "buscar_produtos_semelhantes",
        lambda c, vetor, limite, maxima: [
            _peca("Terno La", 0.30),
            _peca("Camisa Social", 0.32),
            _peca("Tenis", 0.39),  # longe demais da melhor: fica de fora
        ],
    )
    f = Ferramentas(None, UsuarioAtual(id_auth=uuid4()), vetorizar=lambda texto: VETOR)
    pecas = f.executar("buscar_produto", {"descricao": "roupa para casamento"})["pecas"]
    assert [p["nome"] for p in pecas] == ["Terno La", "Camisa Social"]
    assert all("distancia" not in p for p in pecas)


def test_sem_embedding_a_busca_por_palavras_continua(monkeypatch):
    monkeypatch.setattr(
        modulo.repositorio, "buscar_produtos", lambda c, termos, limite: [_peca("Camisa")]
    )

    def falha(texto):
        raise embeddings.ErroEmbedding("HTTP 503")

    f = Ferramentas(None, UsuarioAtual(id_auth=uuid4()), vetorizar=falha)
    assert [p["nome"] for p in f.executar("buscar_produto", {"descricao": "camisa"})["pecas"]] == [
        "Camisa"
    ]
