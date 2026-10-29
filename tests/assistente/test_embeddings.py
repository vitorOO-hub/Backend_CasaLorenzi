from uuid import uuid4

import httpx
import pytest

from app.assistente import embeddings, ferramentas
from app.core.config import Settings
from app.core.papeis import Papel, UsuarioAtual


def test_texto_produto_usa_apenas_atributos_de_catalogo():
    texto = embeddings.texto_produto(
        {
            "nome": "Camisa",
            "categoria": "camisas",
            "cores": ["azul", "branco"],
            "tecido": "linho",
            "id_cliente": "nao incluir",
        }
    )

    assert "produto: Camisa" in texto
    assert "cores: ['azul', 'branco']" in texto
    assert "linho" in texto
    assert "nao incluir" not in texto


def test_gerar_envia_chave_no_header_e_dimensao_correta(monkeypatch):
    requisicao = {}
    valores = [0.25] * embeddings.DIMENSOES

    class ClienteFalso:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, url, *, headers, json):
            requisicao.update(url=url, headers=headers, json=json)
            return httpx.Response(
                200,
                json={"embedding": {"values": valores}},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(embeddings.httpx, "Client", lambda **_kwargs: ClienteFalso())

    resultado = embeddings.gerar("camisa azul", "segredo-teste")

    assert resultado == valores
    assert requisicao["headers"]["x-goog-api-key"] == "segredo-teste"
    assert requisicao["json"]["outputDimensionality"] == 768
    assert "segredo-teste" not in requisicao["url"]


def test_gerar_rejeita_resposta_com_dimensao_incorreta(monkeypatch):
    class ClienteFalso:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, *_args, **_kwargs):
            return httpx.Response(
                200,
                json={"embedding": {"values": [0.1]}},
                request=httpx.Request("POST", embeddings.URL_EMBEDDING),
            )

    monkeypatch.setattr(embeddings.httpx, "Client", lambda **_kwargs: ClienteFalso())

    with pytest.raises(embeddings.EmbeddingIndisponivel):
        embeddings.gerar("consulta", "segredo-teste")


def test_consultar_catalogo_usa_embeddings_somente_quando_busca_literal_falha(monkeypatch):
    admin = UsuarioAtual(id_auth=uuid4(), papel=Papel.ADMIN)
    resultado_lexico = {"total": 0, "itens": []}
    chamado = {}
    monkeypatch.setattr(
        ferramentas.catalogo,
        "listar_para_assistente",
        lambda *_args, **_kwargs: resultado_lexico,
    )
    monkeypatch.setattr(ferramentas.catalogo, "tem_embeddings", lambda *_args: True)
    monkeypatch.setattr(
        embeddings,
        "gerar",
        lambda texto, chave: chamado.update(texto=texto, chave=chave) or [0.2] * 768,
    )
    monkeypatch.setattr(
        ferramentas.catalogo,
        "buscar_semantico",
        lambda _c, _u, vetor, *, limite: {"total": 1, "itens": [vetor], "limite": limite},
    )
    config = Settings(
        _env_file=None,
        database_url="postgresql://localhost/teste",
        gemini_api_key="chave-teste",
    )

    encontrado = ferramentas.executar(
        None, admin, "consultar_catalogo", {"busca": "camisa azul leve"}, config
    )

    assert len(encontrado["itens"][0]) == 768
    assert encontrado["limite"] == 5
    assert chamado == {"texto": "camisa azul leve", "chave": config.gemini_api_key}


def test_consultar_catalogo_prefere_resultados_literais(monkeypatch):
    admin = UsuarioAtual(id_auth=uuid4(), papel=Papel.ADMIN)
    resultado = {"total": 1, "itens": [{"nome": "Camisa Azul"}]}
    monkeypatch.setattr(
        ferramentas.catalogo, "listar_para_assistente", lambda *_args, **_kwargs: resultado
    )
    monkeypatch.setattr(
        embeddings,
        "gerar",
        lambda *_args: pytest.fail("nao deve gerar embedding com resultado literal"),
    )

    assert ferramentas.executar(
        None, admin, "consultar_catalogo", {"busca": "Camisa Azul"}
    ) == resultado


def test_consultar_catalogo_nao_chama_gemini_sem_produtos_indexados(monkeypatch):
    admin = UsuarioAtual(id_auth=uuid4(), papel=Papel.ADMIN)
    resultado = {"total": 0, "itens": []}
    monkeypatch.setattr(
        ferramentas.catalogo, "listar_para_assistente", lambda *_args, **_kwargs: resultado
    )
    monkeypatch.setattr(ferramentas.catalogo, "tem_embeddings", lambda *_args: False)
    monkeypatch.setattr(
        embeddings,
        "gerar",
        lambda *_args: pytest.fail("nao deve chamar Gemini antes da carga dos vetores"),
    )
    config = Settings(
        _env_file=None,
        database_url="postgresql://localhost/teste",
        gemini_api_key="chave-teste",
    )

    assert ferramentas.executar(
        None, admin, "consultar_catalogo", {"busca": "camisa azul"}, config
    ) == resultado


def test_busca_semantica_retorna_atributos_que_comprovam_a_caracteristica():
    linha = {
        "id_produto": uuid4(),
        "nome": "Camisa de linho",
        "categoria": "camisa",
        "preco": 100,
        "skus": [],
        "variacoes": 0,
        "estoque_rede": 0,
        "tipo": "camisa",
        "colecao": "verao",
        "cores": ["azul"],
        "tecido": "linho",
        "tecelagem": None,
        "costurado_em": None,
        "nota": None,
    }

    class Resultado:
        def mappings(self):
            return self

        def __iter__(self):
            return iter([linha])

    class Conexao:
        def execute(self, consulta, parametros):
            assert "produto.tecido" in str(consulta)
            assert "produto.cores" in str(consulta)
            assert parametros["limite"] == 5
            return Resultado()

    usuario = UsuarioAtual(id_auth=uuid4(), papel=Papel.ADMIN)
    resultado = ferramentas.catalogo.buscar_semantico(
        Conexao(), usuario, [0.2] * embeddings.DIMENSOES
    )

    assert resultado["itens"][0]["tecido"] == "linho"
    assert resultado["itens"][0]["cores"] == ["azul"]
