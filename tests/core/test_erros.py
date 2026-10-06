import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.erros import ErroDeNegocio, registrar_tratadores


class NaoEncontrado(ErroDeNegocio):
    status_code = 404
    detalhe = "Registro nao encontrado"


class Conflito(ErroDeNegocio):
    status_code = 409
    detalhe = "Estado nao permite a acao"


@pytest.fixture
def cliente() -> TestClient:
    app = FastAPI()
    registrar_tratadores(app)

    @app.get("/nao-encontrado")
    def nao_encontrado():
        raise NaoEncontrado

    @app.get("/conflito")
    def conflito():
        raise Conflito

    @app.get("/generico")
    def generico():
        raise ErroDeNegocio

    return TestClient(app)


def test_subclasses_viram_resposta_com_status_e_mensagem_em_portugues(cliente):
    resposta = cliente.get("/nao-encontrado")
    assert (resposta.status_code, resposta.json()) == (404, {"detail": "Registro nao encontrado"})
    resposta = cliente.get("/conflito")
    assert (resposta.status_code, resposta.json()) == (409, {"detail": "Estado nao permite a acao"})


def test_erro_de_negocio_sem_status_proprio_vira_400(cliente):
    resposta = cliente.get("/generico")
    assert (resposta.status_code, resposta.json()) == (400, {"detail": "Requisicao invalida"})
