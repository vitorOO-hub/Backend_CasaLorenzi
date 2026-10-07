import psycopg
import pytest

from tests.banco.apoio import tenta

pytestmark = pytest.mark.banco


def test_coluna_id_loja_existe_e_aceita_nulo(conn):
    nulo = conn.execute(
        "SELECT is_nullable FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = 'atendimento' AND column_name = 'id_loja'"
    ).fetchone()
    assert nulo == ("YES",)


def test_trigger_preenche_a_loja_a_partir_do_pedido(conn, fab):
    loja = fab.loja()
    cliente = fab.usuario("cliente")
    pedido = fab.pedido(loja=loja, cliente=cliente)
    atendimento = fab.atendimento(cliente=cliente, pedido=pedido)
    gravada = conn.execute(
        "SELECT id_loja FROM atendimento WHERE id_atendimento = %s", (atendimento,)
    ).fetchone()[0]
    assert gravada == loja


def test_loja_informada_e_mantida(conn, fab):
    loja_do_pedido, loja_informada = fab.loja(), fab.loja()
    cliente = fab.usuario("cliente")
    pedido = fab.pedido(loja=loja_do_pedido, cliente=cliente)
    atendimento = fab.atendimento(cliente=cliente, loja=loja_informada, pedido=pedido)
    gravada = conn.execute(
        "SELECT id_loja FROM atendimento WHERE id_atendimento = %s", (atendimento,)
    ).fetchone()[0]
    assert gravada == loja_informada


def test_sem_pedido_a_loja_fica_nula(conn, fab):
    atendimento = fab.atendimento(cliente=fab.usuario("cliente"))
    gravada = conn.execute(
        "SELECT id_loja FROM atendimento WHERE id_atendimento = %s", (atendimento,)
    ).fetchone()[0]
    assert gravada is None


def test_loja_inexistente_e_recusada_pela_fk(conn, fab):
    cliente = fab.usuario("cliente")
    resultado = tenta(
        conn,
        "UPDATE atendimento SET id_loja = gen_random_uuid() WHERE id_atendimento = %s",
        (fab.atendimento(cliente=cliente),),
    )
    assert isinstance(resultado, psycopg.errors.ForeignKeyViolation)
