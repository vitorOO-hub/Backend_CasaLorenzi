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
        assunto = conexao.execute(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'atendimento' "
            "AND column_name = 'assunto'"
        ).fetchone()[0]
        protocolo = conexao.execute(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'atendimento' "
            "AND column_name = 'protocolo'"
        ).fetchone()[0]
        anexos = conexao.execute(
            "SELECT count(*) FROM pg_tables WHERE schemaname = 'public' "
            "AND tablename = 'chamado_anexo'"
        ).fetchone()[0]
        funcoes = conexao.execute(
            "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'public' AND (p.proname LIKE 'app\\_%' "
            "OR p.proname IN ('hook_claims_token', 'preencher_id_loja_atendimento', "
            "'definir_protocolo_atendimento'))"
        ).fetchone()[0]
        politicas = conexao.execute(
            "SELECT count(*) FROM pg_policies WHERE schemaname = 'public' "
            "AND policyname LIKE '% - %'"
        ).fetchone()[0]
        forcado = conexao.execute(
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relforcerowsecurity"
        ).fetchone()[0]
    return {
        "coluna": coluna,
        "assunto": assunto,
        "protocolo": protocolo,
        "anexos": anexos,
        "funcoes": funcoes,
        "politicas": politicas,
        "forcado": forcado,
    }


def test_downgrade_remove_tudo_e_upgrade_reaplica(banco_migrado):
    url = banco_migrado
    antes = estado(url)
    assert antes["coluna"] == 1
    assert antes["assunto"] == 1
    assert antes["protocolo"] == 1
    assert antes["anexos"] == 1
    # 7 app_* + hook_claims_token + preencher_id_loja_atendimento + definir_protocolo_atendimento
    assert antes["funcoes"] == 10
    # 12 em D1 (7 + 5 de opcoes), 7 em D2, 1 em chamado_anexo e 4 de leitura do estoque
    # (tipos, status e transferencias, e ajustes).
    assert antes["politicas"] == 24
    assert antes["forcado"] >= 20
    try:
        rodar_alembic(url, "downgrade", REVISAO_ANTERIOR)
        depois = estado(url)
        assert depois == {
            "coluna": 0,
            "assunto": 0,
            "protocolo": 0,
            "anexos": 0,
            "funcoes": 0,
            "politicas": 0,
            "forcado": 0,
        }
    finally:
        rodar_alembic(url, "upgrade", "head")
    assert estado(url) == antes
