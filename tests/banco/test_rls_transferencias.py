"""As tabelas de transferencia de estoque nascem trancadas para o front."""

import pytest

from tests.banco.apoio import como, e_erro, tenta

pytestmark = pytest.mark.banco

TABELAS = ["tipo_transferencia_estoque", "status_transferencia_estoque", "transferencia_estoque"]


@pytest.mark.parametrize("tabela", TABELAS)
def test_rls_ligado_e_forcado(conn, tabela):
    ligado, forcado = conn.execute(
        "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
        "WHERE relname = %s AND relnamespace = 'public'::regnamespace",
        (tabela,),
    ).fetchone()
    assert ligado and forcado


@pytest.mark.parametrize("role", ["anon", "authenticated"])
@pytest.mark.parametrize("tabela", TABELAS)
def test_front_nao_le_nem_escreve(conn, tabela, role):
    with como(conn, role=role):
        assert e_erro(tenta(conn, f"SELECT 1 FROM {tabela} LIMIT 1"))
        assert e_erro(tenta(conn, f"DELETE FROM {tabela}"))


@pytest.mark.parametrize("tabela", TABELAS)
def test_nenhuma_policy_abre_a_tabela_ao_front(conn, tabela):
    assert (
        conn.execute("SELECT count(*) FROM pg_policies WHERE tablename = %s", (tabela,)).fetchone()[
            0
        ]
        == 0
    )
