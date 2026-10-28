# ruff: noqa: E501  (linhas de teste com URLs e payloads)
"""Login por CPF pela API de verdade, contra um Postgres real (Supabase Auth falso)."""

import json
import random
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.acesso import service as acesso
from app.acesso.router import get_login_auth
from app.core.config import Settings
from app.main import criar_app
from tests.auth_util import SUPABASE_URL

pytestmark = pytest.mark.banco

CPF = "/api/v1/acesso/entrar-cpf"


class LoginFalso:
    """No lugar do Supabase Auth: confere a senha e diz para qual e-mail foi pedida a sessao."""

    def __init__(self):
        self.pedidos: list[str] = []

    def entrar(self, email, senha):
        self.pedidos.append(email)
        if senha != "Senha123":
            raise acesso.CpfOuSenhaIncorretos
        return {
            "access_token": "token-de-acesso",
            "refresh_token": "token-de-renovacao",
            "expires_in": 3600,
        }


def _cpf():
    return "".join(random.choices("0123456789", k=11))


@pytest.fixture
def cena(banco_migrado):
    sufixo = uuid4().hex[:6].lower()
    cpf_cliente, cpf_equipe = _cpf(), _cpf()
    with psycopg.connect(banco_migrado, autocommit=True) as pg:
        loja = pg.execute(
            "INSERT INTO loja (codigo, nome, ativa) VALUES (%s, %s, true) RETURNING id_loja",
            (f"C{sufixo.upper()}", f"Loja Cpf {sufixo}"),
        ).fetchone()[0]
        # Cliente que se cadastrou pelo site: o trigger do auth.users cria o cadastro.
        email = f"cliente.{sufixo}@teste.local"
        meta = {
            "cadastro_cliente": "true",
            "nome": "Cliente Cpf",
            "telefone": "11999990000",
            "rua": "Rua A",
            "bairro": "Centro",
            "numero_endereco": "1",
            "cep": "01001000",
            "documento": cpf_cliente,
        }
        auth_cliente = pg.execute(
            "INSERT INTO auth.users (email, raw_user_meta_data) VALUES (%s, %s::jsonb) RETURNING id",
            (email, json.dumps(meta)),
        ).fetchone()[0]
        # Pessoa da equipe com CPF: nao entra por CPF (equipe usa e-mail).
        auth_equipe = uuid4()
        pg.execute(
            "INSERT INTO auth.users (id, email) VALUES (%s, %s)",
            (auth_equipe, f"equipe.{sufixo}@teste.local"),
        )
        if pg.execute("SELECT 1 FROM usuario WHERE auth_user_id = %s", (auth_equipe,)).fetchone():
            pg.execute(
                "UPDATE usuario SET id_tipo_usuario = (SELECT id_tipo_usuario FROM tipo_usuario WHERE codigo = 'atendente'),"
                " id_loja = %s, documento = %s, rua = NULL, bairro = NULL, numero_endereco = NULL, cep = NULL"
                " WHERE auth_user_id = %s",
                (loja, cpf_equipe, auth_equipe),
            )
        else:
            pg.execute(
                "INSERT INTO usuario (id_tipo_usuario, id_loja, auth_user_id, nome, email, documento) VALUES"
                " ((SELECT id_tipo_usuario FROM tipo_usuario WHERE codigo = 'atendente'), %s, %s, 'Equipe Cpf', %s, %s)",
                (loja, auth_equipe, f"equipe.{sufixo}@teste.local", cpf_equipe),
            )
        app = criar_app(
            Settings(_env_file=None, database_url=banco_migrado, supabase_url=SUPABASE_URL)
        )
        login = LoginFalso()
        app.dependency_overrides[get_login_auth] = lambda: login
        yield TestClient(app), login, {"cpf": cpf_cliente, "cpf_equipe": cpf_equipe, "email": email}

        auths = [auth_cliente, auth_equipe]
        pg.execute("DELETE FROM usuario WHERE auth_user_id = ANY(%s)", (auths,))
        pg.execute("DELETE FROM auth.users WHERE id = ANY(%s)", (auths,))
        pg.execute("DELETE FROM loja WHERE id_loja = %s", (loja,))


def test_cliente_entra_por_cpf_e_recebe_so_os_tokens(cena):
    http, login, ids = cena
    cpf = ids["cpf"]
    r = http.post(
        CPF, json={"cpf": f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}", "senha": "Senha123"}
    )
    assert r.status_code == 200, r.text
    assert r.json() == {
        "access_token": "token-de-acesso",
        "refresh_token": "token-de-renovacao",
        "expires_in": 3600,
        "token_type": "bearer",
    }
    assert login.pedidos == [ids["email"]]
    assert ids["email"] not in r.text


@pytest.mark.parametrize("caso", ["senha_errada", "cpf_desconhecido", "cpf_da_equipe"])
def test_falhas_do_login_por_cpf_tem_a_mesma_resposta(cena, caso):
    http, login, ids = cena
    cpf, senha = {
        "senha_errada": (ids["cpf"], "Errada123"),
        "cpf_desconhecido": ("00000000191", "Senha123"),
        "cpf_da_equipe": (ids["cpf_equipe"], "Senha123"),
    }[caso]
    r = http.post(CPF, json={"cpf": cpf, "senha": senha})
    assert r.status_code == 401
    assert r.json()["detail"] == "CPF ou senha incorretos."
    if caso != "senha_errada":
        assert login.pedidos == []
