from uuid import uuid4

import pytest

from tests.banco.apoio import como

pytestmark = pytest.mark.banco


def test_papeis_do_supabase_existem(conn):
    nomes = {
        linha[0]
        for linha in conn.execute(
            "SELECT rolname FROM pg_roles "
            "WHERE rolname IN ('anon', 'authenticated', 'service_role', 'supabase_auth_admin')"
        )
    }
    assert nomes == {"anon", "authenticated", "service_role", "supabase_auth_admin"}


def test_auth_uid_le_o_sub_das_claims(conn):
    sub = uuid4()
    with como(conn, sub=sub):
        assert conn.execute("SELECT auth.uid()").fetchone()[0] == sub


def test_auth_jwt_devolve_as_claims(conn):
    with como(conn, papel="admin"):
        claims = conn.execute("SELECT auth.jwt()").fetchone()[0]
    assert claims["papel"] == "admin"


def test_schema_do_projeto_foi_aplicado(conn):
    tabelas = {
        linha[0]
        for linha in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    }
    assert {"loja", "usuario", "pedido", "estoque", "atendimento", "mensagem"} <= tabelas
    assert conn.execute("SELECT count(*) FROM alembic_version").fetchone()[0] == 1


def test_opcoes_de_dominio_vieram_semeadas(conn):
    tipos = conn.execute(
        "SELECT count(*) FROM tipo_usuario WHERE codigo IN ('cliente', 'diretor')"
    ).fetchone()[0]
    assert tipos == 2
    resolvido = conn.execute(
        "SELECT count(*) FROM status_atendimento WHERE codigo = 'resolvido'"
    ).fetchone()[0]
    assert resolvido == 1
