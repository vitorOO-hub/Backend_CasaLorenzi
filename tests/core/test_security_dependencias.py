from typing import Annotated
from uuid import uuid4

import httpx
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.erros import registrar_tratadores
from app.core.erros_auth import SemPermissao
from app.core.jwks import ProvedorChaves
from app.core.papeis import Papel, UsuarioAtual
from app.core.security import garantir_escopo_de_loja, get_current_user, requer_papel
from tests.auth_util import SUPABASE_URL, URL_JWKS, ParDeChaves, provedor_para
from tests.conftest import DATABASE_URL_TESTE


def montar_app(par: ParDeChaves, *, provedor=None) -> FastAPI:
    settings = Settings(
        _env_file=None,
        database_url=DATABASE_URL_TESTE,
        supabase_url=SUPABASE_URL,
    )
    app = FastAPI()
    app.state.settings = settings
    app.state.provedor_chaves = provedor or provedor_para(par)
    registrar_tratadores(app)

    @app.get("/eu")
    def eu(usuario: Annotated[UsuarioAtual, Depends(get_current_user)]):
        return {"id": str(usuario.id_auth), "papel": usuario.papel}

    @app.get("/so-gerente", dependencies=[Depends(requer_papel(Papel.GERENTE_LOJA, Papel.ADMIN))])
    def so_gerente():
        return {"ok": True}

    return app


def cabecalho(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def par() -> ParDeChaves:
    return ParDeChaves()


@pytest.fixture
def cliente(par) -> TestClient:
    return TestClient(montar_app(par))


# ---- get_current_user --------------------------------------------------------------------


def test_sem_cabecalho_responde_401(cliente):
    resposta = cliente.get("/eu")
    assert resposta.status_code == 401
    assert resposta.headers["www-authenticate"] == "Bearer"


def test_esquema_diferente_de_bearer_responde_401(cliente):
    assert cliente.get("/eu", headers={"Authorization": "Basic YWJjOmRlZg=="}).status_code == 401


def test_token_valido_devolve_o_usuario(cliente, par):
    sub = uuid4()
    resposta = cliente.get("/eu", headers=cabecalho(par.emitir(sub=str(sub))))
    assert resposta.status_code == 200
    assert resposta.json() == {"id": str(sub), "papel": None}


def test_token_invalido_nao_vaza_o_motivo(cliente):
    resposta = cliente.get("/eu", headers=cabecalho("lixo"))
    assert resposta.status_code == 401
    assert resposta.json() == {"detail": "Token invalido ou ausente"}


def test_jwks_fora_do_ar_responde_503(par):
    def buscar():
        raise httpx.ConnectError("sem rede")

    app = montar_app(par, provedor=ProvedorChaves(URL_JWKS, buscar=buscar))
    resposta = TestClient(app).get("/eu", headers=cabecalho(par.emitir()))
    assert resposta.status_code == 503


def test_sem_supabase_url_responde_503(par):
    app = montar_app(par)
    del app.state.provedor_chaves
    app.state.settings = Settings(_env_file=None, database_url=DATABASE_URL_TESTE)
    resposta = TestClient(app).get("/eu", headers=cabecalho(par.emitir()))
    assert resposta.status_code == 503


# ---- requer_papel ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("claims", "esperado"),
    [
        ({}, 403),
        ({"papel": "atendente", "loja_id": str(uuid4())}, 403),
        ({"papel": "gerente_loja", "loja_id": str(uuid4())}, 200),
        ({"papel": "admin"}, 200),
    ],
    ids=["cliente", "atendente", "gerente", "admin"],
)
def test_requer_papel(cliente, par, claims, esperado):
    resposta = cliente.get("/so-gerente", headers=cabecalho(par.emitir(**claims)))
    assert resposta.status_code == esperado


def test_requer_papel_sem_token_responde_401(cliente):
    assert cliente.get("/so-gerente").status_code == 401


# ---- escopo de loja ----------------------------------------------------------------------


def test_garantir_escopo_de_loja():
    loja = uuid4()
    gerente = UsuarioAtual(id_auth=uuid4(), papel=Papel.GERENTE_LOJA, id_loja=loja)
    garantir_escopo_de_loja(gerente, loja)
    with pytest.raises(SemPermissao):
        garantir_escopo_de_loja(gerente, uuid4())
    garantir_escopo_de_loja(UsuarioAtual(id_auth=uuid4(), papel=Papel.ADMIN), uuid4())
    with pytest.raises(SemPermissao):
        garantir_escopo_de_loja(UsuarioAtual(id_auth=uuid4()), loja)
