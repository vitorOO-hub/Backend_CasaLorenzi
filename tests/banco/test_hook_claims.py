import json
from uuid import uuid4

import pytest

pytestmark = pytest.mark.banco

CLAIMS_BASE = {"role": "authenticated", "aud": "authenticated", "exp": 9999999999}


def chamar_hook(conn, auth_user_id, extras=None) -> dict:
    claims = {**CLAIMS_BASE, "sub": str(auth_user_id), **(extras or {})}
    evento = {"user_id": str(auth_user_id), "claims": claims}
    retorno = conn.execute(
        "SELECT public.hook_claims_token(%s::jsonb)", (json.dumps(evento),)
    ).fetchone()[0]
    return retorno["claims"]


def test_gerente_recebe_papel_e_loja(conn, fab):
    loja = fab.loja()
    gerente = fab.usuario("gerente_loja", loja=loja)
    claims = chamar_hook(conn, gerente.auth)
    assert claims["papel"] == "gerente_loja"
    assert claims["loja_id"] == str(loja)


@pytest.mark.parametrize("tipo", ["atendente", "operador_estoque"])
def test_equipe_de_loja_recebe_papel_e_loja(conn, fab, tipo):
    loja = fab.loja()
    usuario = fab.usuario(tipo, loja=loja)
    claims = chamar_hook(conn, usuario.auth)
    assert claims["papel"] == tipo
    assert claims["loja_id"] == str(loja)


def test_diretor_vira_admin_e_nao_leva_loja(conn, fab):
    diretor = fab.usuario("diretor", loja=fab.loja())
    claims = chamar_hook(conn, diretor.auth)
    assert claims["papel"] == "admin"
    assert "loja_id" not in claims


def test_cliente_nao_recebe_papel_nem_loja(conn, fab):
    cliente = fab.usuario("cliente")
    claims = chamar_hook(conn, cliente.auth)
    assert "papel" not in claims
    assert "loja_id" not in claims


def test_usuario_inativo_fica_sem_papel(conn, fab):
    gerente = fab.usuario("gerente_loja", loja=fab.loja(), ativo=False)
    claims = chamar_hook(conn, gerente.auth)
    assert "papel" not in claims
    assert "loja_id" not in claims


def test_usuario_inexistente_fica_sem_papel(conn):
    claims = chamar_hook(conn, uuid4())
    assert "papel" not in claims


def test_atendente_sem_loja_cadastrada_sai_sem_loja(conn, fab):
    atendente = fab.usuario("atendente")
    claims = chamar_hook(conn, atendente.auth)
    assert claims["papel"] == "atendente"
    assert "loja_id" not in claims


def test_claims_padrao_do_token_sao_preservadas(conn, fab):
    cliente = fab.usuario("cliente")
    claims = chamar_hook(conn, cliente.auth)
    assert claims["sub"] == str(cliente.auth)
    assert claims["role"] == "authenticated"
    assert claims["aud"] == "authenticated"
    assert claims["exp"] == 9999999999


def test_papel_e_loja_que_ja_vinham_no_token_sao_descartados(conn, fab):
    cliente = fab.usuario("cliente")
    claims = chamar_hook(conn, cliente.auth, {"papel": "admin", "loja_id": str(uuid4())})
    assert "papel" not in claims
    assert "loja_id" not in claims


@pytest.mark.parametrize(
    ("papel_do_banco", "esperado"),
    [("authenticated", False), ("anon", False), ("supabase_auth_admin", True)],
)
def test_so_o_supabase_auth_admin_executa_o_hook(conn, papel_do_banco, esperado):
    autorizado = conn.execute(
        "SELECT has_function_privilege(%s, 'public.hook_claims_token(jsonb)', 'EXECUTE')",
        (papel_do_banco,),
    ).fetchone()[0]
    assert autorizado is esperado
