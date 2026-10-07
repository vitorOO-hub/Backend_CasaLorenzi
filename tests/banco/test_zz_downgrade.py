import psycopg
import pytest

from tests.banco.conftest import rodar_alembic

pytestmark = pytest.mark.banco

REVISAO_ANTERIOR = "20261006213000"


def estado(url: str) -> dict:
    with psycopg.connect(url) as conexao:
        coluna = conexao.execute(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'atendimento' "
            "AND column_name = 'id_loja'"
        ).fetchone()[0]
        funcoes = conexao.execute(
            "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'public' AND (p.proname LIKE 'app\\_%' "
            "OR p.proname IN ('hook_claims_token', 'preencher_id_loja_atendimento'))"
        ).fetchone()[0]
        politicas = conexao.execute(
            "SELECT count(*) FROM pg_policies WHERE schemaname = 'public' "
            "AND policyname LIKE '% - %'"
        ).fetchone()[0]
        forcado = conexao.execute(
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relforcerowsecurity"
        ).fetchone()[0]
    return {"coluna": coluna, "funcoes": funcoes, "politicas": politicas, "forcado": forcado}


def test_downgrade_remove_tudo_e_upgrade_reaplica(banco_migrado):
    url = banco_migrado
    antes = estado(url)
    assert antes["coluna"] == 1
    assert antes["funcoes"] == 9  # 7 app_* + hook_claims_token + preencher_id_loja_atendimento
    assert antes["politicas"] == 19  # 12 em D1 (7 + 5 de opcoes) e 7 em D2
    assert antes["forcado"] >= 20
    try:
        rodar_alembic(url, "downgrade", REVISAO_ANTERIOR)
        depois = estado(url)
        assert depois == {"coluna": 0, "funcoes": 0, "politicas": 0, "forcado": 0}
    finally:
        rodar_alembic(url, "upgrade", "head")
    assert estado(url) == antes
