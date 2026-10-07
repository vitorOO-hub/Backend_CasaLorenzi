from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.erros import registrar_tratadores
from app.core.erros_auth import AutenticacaoIndisponivel, NaoAutenticado, SemPermissao


def montar_cliente(erro: Exception) -> TestClient:
    app = FastAPI()
    registrar_tratadores(app)

    @app.get("/falha")
    def falha():
        raise erro

    return TestClient(app)


def test_nao_autenticado_responde_401_com_cabecalho():
    resposta = montar_cliente(NaoAutenticado()).get("/falha")
    assert resposta.status_code == 401
    assert resposta.headers["www-authenticate"] == "Bearer"
    assert resposta.json() == {"detail": "Token invalido ou ausente"}


def test_sem_permissao_responde_403():
    resposta = montar_cliente(SemPermissao()).get("/falha")
    assert resposta.status_code == 403
    assert resposta.json() == {"detail": "Voce nao tem permissao para esta acao"}


def test_autenticacao_indisponivel_responde_503():
    resposta = montar_cliente(AutenticacaoIndisponivel()).get("/falha")
    assert resposta.status_code == 503
    assert resposta.json() == {"detail": "Autenticacao temporariamente indisponivel"}
