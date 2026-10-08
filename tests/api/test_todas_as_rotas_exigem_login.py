"""Rede de seguranca: com o Supabase configurado, NENHUMA rota responde sem token.

Percorre todas as rotas registradas (as de hoje e as que vierem) e chama cada uma sem credencial.
So a saude, a documentacao do FastAPI e o estoque do catalogo ficam abertos. Se alguem criar
uma rota nova e esquecer de trancar, este teste quebra.
"""

import re
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.db import get_executar
from app.main import criar_app
from tests.auth_util import SUPABASE_URL
from tests.conftest import DATABASE_URL_TESTE

# O estoque do catalogo e publico como o proprio catalogo: so le saldo de pecas ativas, sem dado
# de cliente, e a loja precisa dele para quem navega sem login.
ABERTAS = {
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/docs/oauth2-redirect",
    "/api/v1/cliente/catalogo/estoque",
}
METODOS = {"get", "post", "put", "patch", "delete"}


def rotas(app):
    esquema = app.openapi()
    for caminho, operacoes in esquema["paths"].items():
        for metodo in operacoes:
            if metodo in METODOS and caminho not in ABERTAS:
                yield metodo.upper(), caminho


@pytest.fixture(scope="module")
def cliente():
    app = criar_app(
        Settings(_env_file=None, database_url=DATABASE_URL_TESTE, supabase_url=SUPABASE_URL)
    )

    # Se alguma rota deixasse passar, nao chegaria a tocar no banco: este executor explode.
    def sem_banco():
        def executar(_operacao):
            raise AssertionError("rota aberta chegou ao banco sem token")

        return executar

    app.dependency_overrides[get_executar] = sem_banco
    return TestClient(app, raise_server_exceptions=False)


def preencher(caminho: str) -> str:
    return re.sub(r"\{[^}]+\}", str(uuid4()), caminho)


def test_ha_rotas_para_verificar(cliente):
    assert len(list(rotas(cliente.app))) > 80


def test_toda_rota_sem_token_responde_401(cliente):
    abertas = []
    for metodo, caminho in rotas(cliente.app):
        resposta = cliente.request(metodo, preencher(caminho), json={})
        if resposta.status_code != 401:
            abertas.append(f"{metodo} {caminho} -> {resposta.status_code}")
    assert abertas == [], "rotas sem trava de login:\n" + "\n".join(abertas)


def test_token_lixo_tambem_e_401(cliente):
    for cabecalho in ("Bearer abc", "Bearer ", "Basic xyz", "Bearer " + "a" * 9000):
        resposta = cliente.get(
            "/api/v1/painel/gerencia/pendencias", headers={"Authorization": cabecalho}
        )
        assert resposta.status_code == 401, cabecalho[:20]
