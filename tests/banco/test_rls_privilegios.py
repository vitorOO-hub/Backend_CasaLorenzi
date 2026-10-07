from uuid import uuid4

import pytest
from psycopg import sql

from tests.banco.apoio import como, e_erro, tenta
from tests.banco.fabrica import Usuario

pytestmark = pytest.mark.banco

TABELAS_SENSIVEIS = [
    "usuario",
    "atendimento",
    "atendimento_item",
    "mensagem",
    "avaliacao_atendimento",
    "pedido",
    "item_pedido",
    "pagamento",
    "estoque",
    "movimentacao_estoque",
]

ASSINATURAS = [
    "app_usuario_id()",
    "app_papel()",
    "app_loja_id()",
    "app_papel_na_loja(uuid, text[])",
    "app_pode_ver_atendimento(uuid)",
    "app_atendimento_aceita_mensagem(uuid)",
    "app_pode_avaliar_atendimento(uuid)",
]

PRIVILEGIOS_DE_ESCRITA = (
    "('INSERT'), ('UPDATE'), ('DELETE'), ('TRUNCATE'), ('REFERENCES'), ('TRIGGER')"
)


def como_usuario(conn, usuario: Usuario):
    papel = {"diretor": "admin"}.get(usuario.tipo, usuario.tipo)
    papel = None if papel == "cliente" else papel
    loja = None if papel in (None, "admin") else usuario.loja
    return como(conn, sub=usuario.auth, papel=papel, loja=loja)


def test_rls_ligado_e_forcado_em_todas_as_tabelas(conn):
    linhas = conn.execute(
        """
        SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relname <> 'alembic_version'
        """
    ).fetchall()
    assert len(linhas) >= 20
    assert [nome for nome, rls, forca in linhas if not (rls and forca)] == []


@pytest.mark.parametrize("tabela", TABELAS_SENSIVEIS)
def test_anon_nao_le_tabelas_sensiveis(conn, tabela):
    with como(conn, role="anon"):
        resultado = tenta(conn, sql.SQL("SELECT 1 FROM {} LIMIT 1").format(sql.Identifier(tabela)))
    assert e_erro(resultado)


def test_anon_so_tem_privilegio_no_catalogo(conn):
    linhas = conn.execute(
        """
        SELECT c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind = 'r'
          AND has_any_column_privilege('anon', c.oid, 'SELECT, INSERT, UPDATE, REFERENCES')
        """
    ).fetchall()
    assert {linha[0] for linha in linhas} == {"loja", "produto", "variacao_produto"}


def test_anon_ainda_le_o_catalogo_publico(conn, fab):
    ativa = fab.loja()
    fab.loja(ativa=False)
    with como(conn, role="anon"):
        ids = {linha[0] for linha in tenta(conn, "SELECT id_loja FROM loja")}
    assert ids == {ativa}


def test_authenticated_so_escreve_nas_duas_excecoes(conn):
    linhas = conn.execute(
        f"""
        SELECT c.relname, p.priv
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        CROSS JOIN (VALUES {PRIVILEGIOS_DE_ESCRITA}) AS p(priv)
        WHERE n.nspname = 'public' AND c.relkind = 'r'
          AND has_table_privilege('authenticated', c.oid, p.priv)
        """
    ).fetchall()
    assert set(linhas) <= {("mensagem", "INSERT"), ("avaliacao_atendimento", "INSERT")}


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_ninguem_escreve_em_loja(conn, role):
    with como(conn, role=role):
        for comando in (
            "INSERT INTO loja (codigo, nome) VALUES ('X', 'X')",
            "UPDATE loja SET nome = 'Y'",
            "DELETE FROM loja",
        ):
            assert e_erro(tenta(conn, comando))


@pytest.mark.parametrize("assinatura", ASSINATURAS)
def test_funcoes_auxiliares_so_para_authenticated(conn, assinatura):
    consulta = "SELECT has_function_privilege(%s, %s, 'EXECUTE')"
    nome = f"public.{assinatura}"
    assert conn.execute(consulta, ("authenticated", nome)).fetchone()[0] is True
    assert conn.execute(consulta, ("anon", nome)).fetchone()[0] is False


def test_app_usuario_id_so_devolve_usuario_ativo(conn, fab):
    ativo = fab.usuario("cliente")
    inativo = fab.usuario("cliente", ativo=False)
    with como(conn, sub=ativo.auth):
        assert conn.execute("SELECT public.app_usuario_id()").fetchone()[0] == ativo.id
    with como(conn, sub=inativo.auth):
        assert conn.execute("SELECT public.app_usuario_id()").fetchone()[0] is None
    with como(conn, sub=uuid4()):
        assert conn.execute("SELECT public.app_usuario_id()").fetchone()[0] is None


def test_app_papel_e_loja_leem_as_claims(conn):
    loja = uuid4()
    with como(conn, papel="gerente_loja", loja=loja):
        assert conn.execute("SELECT public.app_papel()").fetchone()[0] == "gerente_loja"
        assert conn.execute("SELECT public.app_loja_id()").fetchone()[0] == loja
    with como(conn):
        assert conn.execute("SELECT public.app_papel()").fetchone()[0] is None
        assert conn.execute("SELECT public.app_loja_id()").fetchone()[0] is None


def papel_na_loja(conn, usuario: Usuario, loja, papeis=("gerente_loja",)) -> bool:
    with como_usuario(conn, usuario):
        consulta = "SELECT public.app_papel_na_loja(%s, %s)"
        return conn.execute(consulta, (loja, list(papeis))).fetchone()[0]


def test_app_papel_na_loja_tabela_verdade(conn, fab):
    loja_a, loja_b = fab.loja(), fab.loja()
    gerente = fab.usuario("gerente_loja", loja=loja_a)
    gerente_inativo = fab.usuario("gerente_loja", loja=loja_a, ativo=False)
    operador = fab.usuario("operador_estoque", loja=loja_a)
    admin = fab.usuario("diretor")
    cliente = fab.usuario("cliente")

    assert papel_na_loja(conn, gerente, loja_a) is True
    assert papel_na_loja(conn, gerente, loja_b) is False
    assert papel_na_loja(conn, gerente, None) is False
    assert papel_na_loja(conn, gerente_inativo, loja_a) is False
    assert papel_na_loja(conn, operador, loja_a) is False
    assert papel_na_loja(conn, operador, loja_a, ("operador_estoque", "gerente_loja")) is True
    assert papel_na_loja(conn, admin, loja_a) is True
    assert papel_na_loja(conn, admin, loja_b) is True
    assert papel_na_loja(conn, cliente, loja_a) is False
