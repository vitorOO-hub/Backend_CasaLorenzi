"""A ligacao conta -> usuario que o script faz, e o token que o hook monta a partir dela."""

import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import pytest

CAMINHO = Path(__file__).resolve().parents[2] / "scripts" / "criar_contas.py"
_spec = importlib.util.spec_from_file_location("criar_contas_banco", CAMINHO)
criar_contas = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(criar_contas)

pytestmark = pytest.mark.banco


def claims_do_hook(conn, auth_user_id) -> dict:
    evento = {
        "user_id": str(auth_user_id),
        "claims": {"sub": str(auth_user_id), "role": "authenticated"},
    }
    return conn.execute(
        "SELECT public.hook_claims_token(%s::jsonb)", (json.dumps(evento),)
    ).fetchone()[0]["claims"]


@pytest.mark.parametrize("conta", criar_contas.CONTAS, ids=lambda c: c.papel)
def test_cada_conta_gera_o_papel_e_a_loja_certos_no_token(conn, fab, conta):
    loja = fab.loja()
    codigo_loja = conn.execute("SELECT codigo FROM loja WHERE id_loja = %s", (loja,)).fetchone()[0]
    id_auth = uuid4()
    email = criar_contas.email_da(conta, "teste.local")

    criar_contas.vincular_usuario(conn, conta, email, str(id_auth), codigo_loja)
    claims = claims_do_hook(conn, id_auth)

    if conta.papel == "cliente":
        assert "papel" not in claims
    else:
        assert claims["papel"] == conta.papel
    if conta.precisa_loja:
        assert claims["loja_id"] == str(loja)
    else:
        assert "loja_id" not in claims


def test_rodar_de_novo_atualiza_a_linha_em_vez_de_duplicar(conn, fab):
    loja = fab.loja()
    codigo_loja = conn.execute("SELECT codigo FROM loja WHERE id_loja = %s", (loja,)).fetchone()[0]
    conta = next(c for c in criar_contas.CONTAS if c.papel == "gerente_loja")
    email = criar_contas.email_da(conta, "teste.local")
    criar_contas.vincular_usuario(conn, conta, email, str(uuid4()), codigo_loja)
    novo = uuid4()
    criar_contas.vincular_usuario(conn, conta, email, str(novo), codigo_loja)

    linhas = conn.execute("SELECT auth_user_id FROM usuario WHERE email = %s", (email,)).fetchall()
    assert linhas == [(novo,)]
