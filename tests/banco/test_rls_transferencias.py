"""As tabelas de transferencia: front so le pela policy (equipe das lojas) e nunca escreve."""

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


@pytest.mark.parametrize("tabela", TABELAS)
def test_anonimo_nao_le_nem_escreve(conn, tabela):
    with como(conn, role="anon"):
        assert e_erro(tenta(conn, f"SELECT 1 FROM {tabela} LIMIT 1"))
        assert e_erro(tenta(conn, f"DELETE FROM {tabela}"))


@pytest.mark.parametrize("tabela", TABELAS)
def test_logado_nunca_escreve(conn, tabela):
    with como(conn, role="authenticated"):
        assert e_erro(tenta(conn, f"DELETE FROM {tabela}"))
        assert e_erro(
            tenta(
                conn,
                f"UPDATE {tabela} SET ativo = false"
                if tabela != "transferencia_estoque"
                else "UPDATE transferencia_estoque SET quantidade = 1",
            )
        )


@pytest.mark.parametrize("tabela", TABELAS)
def test_so_existem_policies_de_leitura(conn, tabela):
    comandos = {
        linha[0]
        for linha in conn.execute("SELECT cmd FROM pg_policies WHERE tablename = %s", (tabela,))
    }
    assert comandos == {"SELECT"}
