"""O script de chamados de exemplo contra um Postgres real, e o que a API devolve para eles."""

import importlib.util
from pathlib import Path

import pytest

from app.chamados import service
from app.core.papeis import Papel, UsuarioAtual

CAMINHO = Path(__file__).resolve().parents[2] / "scripts" / "semear_chamados.py"
_spec = importlib.util.spec_from_file_location("semear_chamados", CAMINHO)
semear_chamados = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(semear_chamados)

pytestmark = pytest.mark.banco


@pytest.fixture
def conn(fab_sa):
    """Mesma transacao da conexao SQLAlchemy: a consulta da API enxerga o que foi semeado."""
    return fab_sa.conn


@pytest.fixture
def fab(fab_sa):
    return fab_sa


@pytest.fixture
def banco_pronto(conn, fab):
    loja = fab.loja()
    codigo = conn.execute("SELECT codigo FROM loja WHERE id_loja = %s", (loja,)).fetchone()[0]
    cliente = fab.usuario("cliente")
    atendente = fab.usuario("atendente", loja=loja)
    # O banco de teste nasce com as tabelas de opcoes, mas sem chamados.
    conn.execute("DELETE FROM atendimento")
    return {"codigo": codigo, "loja": loja, "cliente": cliente, "atendente": atendente}


def test_cria_todos_os_exemplos_com_protocolo_e_conversa(conn, banco_pronto):
    criados = semear_chamados.semear(conn, banco_pronto["codigo"])
    assert criados == len(semear_chamados.EXEMPLOS)
    linhas = conn.execute("SELECT protocolo, id_loja FROM atendimento").fetchall()
    assert len(linhas) == criados
    assert len({p for p, _ in linhas}) == criados
    assert all(loja == banco_pronto["loja"] for _, loja in linhas)
    assert conn.execute("SELECT count(*) FROM mensagem").fetchone()[0] == sum(
        len(e.mensagens) for e in semear_chamados.EXEMPLOS
    )


def test_so_semeia_em_banco_sem_chamados_a_menos_que_force(conn, banco_pronto):
    assert semear_chamados.semear(conn, banco_pronto["codigo"]) > 0
    assert semear_chamados.semear(conn, banco_pronto["codigo"]) == 0
    assert semear_chamados.semear(conn, banco_pronto["codigo"], forcar=True) > 0


def test_a_fila_do_atendente_mostra_o_que_foi_semeado(conn, sa_conn, banco_pronto):
    semear_chamados.semear(conn, banco_pronto["codigo"])
    atendente = banco_pronto["atendente"]
    token = UsuarioAtual(id_auth=atendente.auth, papel=Papel.ATENDENTE, id_loja=atendente.loja)
    escopo = service.montar_escopo(sa_conn, token, None)
    filtros = dict(
        situacao="abertos", prioridade=None, canal=None, categoria=None, limit=50, offset=0
    )
    fila = service.listar(sa_conn, escopo, responsavel="fila", **filtros)
    meus = service.listar(sa_conn, escopo, responsavel="eu", **filtros)
    resumo = service.resumo(sa_conn, escopo)
    assert fila["total"] == 3
    assert fila["itens"][0]["prioridade"]["codigo"] == "urgente"  # urgente primeiro
    assert meus["total"] == 3  # os que a equipe assumiu e ainda estao abertos
    assert resumo["sem_resposta"] == 3 and resumo["resolvidos"] == 1


def test_falta_de_loja_ou_de_equipe_da_erro_claro(conn, banco_pronto):
    with pytest.raises(RuntimeError, match="nao existe"):
        semear_chamados.semear(conn, "LOJA-INEXISTENTE")
