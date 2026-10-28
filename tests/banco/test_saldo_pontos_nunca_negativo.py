"""Regra do Lorenzi+ contra um Postgres real: o saldo de pontos nunca fica negativo."""

from datetime import timedelta

import pytest
from sqlalchemy import text

from app.cliente.vencimento_pontos import CORTE_DA_CARGA

pytestmark = pytest.mark.banco


def saldo(c, cliente):
    return c.execute(
        "SELECT COALESCE(sum(pontos), 0) FROM movimento_pontos WHERE id_usuario = %s", (cliente.id,)
    ).fetchone()[0]


def lancar(c, cliente, tipo, pontos, origem="sistema", quando="now()", vence=None):
    c.execute(
        "INSERT INTO movimento_pontos (id_usuario, tipo, pontos, ocorrido_em, vence_em, descricao,"
        f" origem) VALUES (%s, %s, %s, {quando}, %s, 'teste', %s)",
        (cliente.id, tipo, pontos, vence, origem),
    )


def status(c, codigo):
    return c.execute(
        "SELECT id_status_pedido FROM status_pedido WHERE codigo = %s", (codigo,)
    ).fetchone()[0]


def test_saida_maior_que_o_saldo_para_em_zero(fab_sa):
    c, cliente = fab_sa.conn, fab_sa.usuario("cliente")
    lancar(c, cliente, "credito", 300, vence=None)
    lancar(c, cliente, "resgate", -500)
    assert saldo(c, cliente) == 0
    linha = c.execute(
        "SELECT pontos, descricao FROM movimento_pontos WHERE id_usuario = %s AND tipo = 'resgate'",
        (cliente.id,),
    ).fetchone()
    assert linha[0] == -300 and "limitado ao saldo" in linha[1]


def test_saldo_zerado_nao_grava_saida(fab_sa):
    c, cliente = fab_sa.conn, fab_sa.usuario("cliente")
    lancar(c, cliente, "ajuste", -100)
    assert saldo(c, cliente) == 0
    assert (
        c.execute(
            "SELECT count(*) FROM movimento_pontos WHERE id_usuario = %s", (cliente.id,)
        ).fetchone()[0]
        == 0
    )


def test_compra_cancelada_depois_de_usar_os_pontos_nao_deixa_negativo(fab_sa):
    c, cliente = fab_sa.conn, fab_sa.usuario("cliente")
    loja = fab_sa.loja()
    pedido = fab_sa.pedido(loja=loja, cliente=cliente)
    c.execute(
        "UPDATE pedido SET canal_venda = 'loja', valor_total = 500, id_status_pedido = %s"
        " WHERE id_pedido = %s",
        (status(c, "pago"), pedido),
    )
    lancar(c, cliente, "resgate", -400)  # usou os pontos da compra
    c.execute(
        "UPDATE pedido SET id_status_pedido = %s WHERE id_pedido = %s",
        (status(c, "cancelado"), pedido),
    )
    assert saldo(c, cliente) == 0  # antes da regra: 500 - 400 - 500 = -400


def test_carga_historica_fica_de_fora_e_a_rede_de_seguranca_zera(fab_sa, sa_conn):
    c, cliente = fab_sa.conn, fab_sa.usuario("cliente")
    lancar(c, cliente, "resgate", -250, origem="vulto+")
    assert saldo(c, cliente) == -250
    zerados = sa_conn.execute(text("SELECT public.zerar_saldos_negativos_pontos()")).scalar()
    assert zerados >= 1 and saldo(c, cliente) == 0
    assert sa_conn.execute(text("SELECT public.zerar_saldos_negativos_pontos()")).scalar() == 0


def test_ajuste_que_zera_nao_vira_pontos_que_vencem(fab_sa, sa_conn):
    """Divida perdoada nao vira lote: o credito seguinte vence inteiro, sem passar do saldo."""
    c, cliente = fab_sa.conn, fab_sa.usuario("cliente")
    t0 = CORTE_DA_CARGA + timedelta(days=1)
    lancar(c, cliente, "resgate", -250, origem="vulto+", quando=f"'{t0.isoformat()}'")
    sa_conn.execute(text("SELECT public.zerar_saldos_negativos_pontos()"))
    t1 = t0 + timedelta(days=2)
    c.execute(
        "UPDATE movimento_pontos SET ocorrido_em = %s WHERE id_usuario = %s AND tipo = 'ajuste'",
        (t0 + timedelta(hours=1), cliente.id),
    )
    lancar(c, cliente, "credito", 100, quando=f"'{t1.isoformat()}'", vence=t1 + timedelta(days=365))
    agora = t1 + timedelta(days=366)
    sa_conn.execute(
        text("SELECT public.lancar_vencimentos_pontos(CAST(:c AS uuid), :a)"),
        {"c": str(cliente.id), "a": agora},
    )
    assert saldo(c, cliente) == 0  # venceram os 100 do credito, nem mais nem menos
