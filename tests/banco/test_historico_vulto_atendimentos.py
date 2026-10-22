"""Atendimentos do historico da Vulto: fora das filas, visiveis na ficha, voltam com mensagem nova.
Contra um Postgres real."""

from datetime import UTC, datetime

import pytest

from app.chamados import repositorio as chamados
from app.chat import repositorio as chat
from app.clientes import repositorio as clientes

pytestmark = pytest.mark.banco

ANTIGO = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)


def marcar(conn, id_atendimento):
    conn.execute(
        "UPDATE atendimento SET historico_vulto = true WHERE id_atendimento = %s", (id_atendimento,)
    )


@pytest.fixture
def cena(sa_conn, fab_sa):
    c = fab_sa.conn
    cliente = fab_sa.usuario("cliente")
    atendente = fab_sa.usuario("atendente", loja=fab_sa.loja())
    historico = fab_sa.atendimento(cliente=cliente, canal="whatsapp", aberto_em=ANTIGO)
    marcar(c, historico)
    atual = fab_sa.atendimento(cliente=cliente)
    escopo = chamados.Escopo(id_usuario=atendente.id, id_loja=None, incluir_sem_loja=True)
    return c, cliente, atendente, historico, atual, escopo


def ids(itens):
    return {str(i["id_atendimento"]) for i in itens}


def test_historico_fica_fora_da_fila_e_dos_contadores(sa_conn, cena):
    _, _, _, historico, atual, escopo = cena
    total, itens = chamados.listar(
        sa_conn,
        escopo,
        situacao="todos",
        responsavel="todos",
        prioridade=None,
        canal=None,
        categoria=None,
        limit=50,
        offset=0,
    )
    assert str(atual) in ids(itens) and str(historico) not in ids(itens)
    antes = chamados.resumo(sa_conn, escopo)
    assert antes["sem_resposta"] >= 1  # so o atual conta
    # O historico continua acessivel pelo id (ficha do cliente leva ate ele).
    assert chamados.obter_item(sa_conn, escopo, historico) is not None


def test_historico_aparece_na_ficha_do_cliente_com_a_marca_e_a_situacao_original(sa_conn, cena):
    _, cliente, atendente, historico, atual, _ = cena
    escopo = clientes.Escopo(id_usuario=atendente.id, id_loja=None, incluir_sem_loja=True)
    achada = clientes.ficha(sa_conn, escopo, cliente.id, ver_compras=False)
    por_id = {str(c["id_atendimento"]): c for c in achada["chamados"]}
    assert por_id[str(historico)]["historico_vulto"] is True
    assert por_id[str(historico)]["status_codigo"] == "aberto"
    assert por_id[str(atual)]["historico_vulto"] is False
    assert achada["base"]["chamados_em_aberto"] == 1  # o historico nao conta como em aberto


def test_mensagem_nova_tira_a_marca_e_o_atendimento_volta_para_a_fila(sa_conn, cena):
    c, cliente, _, historico, _, escopo = cena
    c.execute(
        "INSERT INTO mensagem (id_atendimento, id_usuario_remetente, texto) VALUES (%s, %s, 'oi')",
        (historico, cliente.id),
    )
    assert c.execute(
        "SELECT historico_vulto FROM atendimento WHERE id_atendimento = %s", (historico,)
    ).fetchone() == (False,)
    _, itens = chamados.listar(
        sa_conn,
        escopo,
        situacao="todos",
        responsavel="todos",
        prioridade=None,
        canal=None,
        categoria=None,
        limit=50,
        offset=0,
    )
    assert str(historico) in ids(itens)


def test_chat_ao_vivo_nao_lista_o_historico(sa_conn, cena):
    _, _, _, historico, atual, escopo = cena
    _, conversas = chat.listar(
        sa_conn, escopo, secao="todas", apenas_nao_lidas=False, limit=50, offset=0
    )
    assert str(atual) in ids(conversas) and str(historico) not in ids(conversas)


def test_filtro_historico_vulto_lista_so_os_importados(sa_conn, cena):
    _, _, _, historico, atual, escopo = cena
    total, itens = chamados.listar(
        sa_conn,
        escopo,
        situacao="historico_vulto",
        responsavel="todos",
        prioridade=None,
        canal=None,
        categoria=None,
        limit=50,
        offset=0,
    )
    assert ids(itens) == {str(historico)} and total == 1
