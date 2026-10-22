"""E-commerce unificado: pedido novo de vulto e-commerce ou vulto app vai para o e-commerce Casa
Lorenzi; loja fisica e pedidos ja gravados nao mudam. Contra um Postgres real."""

from decimal import Decimal

import pytest

from app.cliente import repositorio
from tests.banco.test_chat_repositorio import SemCommit

pytestmark = pytest.mark.banco


def loja(conn, codigo, nome):
    return conn.execute(
        "INSERT INTO loja (codigo, nome) VALUES (%s, %s) "
        "ON CONFLICT (codigo) DO UPDATE SET nome = loja.nome RETURNING id_loja",
        (codigo, nome),
    ).fetchone()[0]


def lojas(conn):
    return {
        "site": loja(conn, "LOJA-VULTO-E-COMMERCE", "vulto e-commerce"),
        "app": loja(conn, "LOJA-VULTO-APP", "vulto app"),
        "ecommerce": loja(conn, "E-COMMERCE-CASA-LORENZI", "E-commerce Casa Lorenzi"),
    }


def loja_do_pedido(conn, pedido):
    return conn.execute("SELECT id_loja FROM pedido WHERE id_pedido = %s", (pedido,)).fetchone()[0]


def test_pedido_novo_de_site_ou_app_da_vulto_vai_para_o_ecommerce(conn, fab):
    lj = lojas(conn)
    cliente = fab.usuario("cliente")
    for origem in ("site", "app"):
        assert loja_do_pedido(conn, fab.pedido(loja=lj[origem], cliente=cliente)) == lj["ecommerce"]


def test_pedido_de_loja_fisica_continua_na_loja(conn, fab):
    lojas(conn)
    fisica = fab.loja()
    pedido = fab.pedido(loja=fisica, cliente=fab.usuario("cliente"))
    assert loja_do_pedido(conn, pedido) == fisica


def test_pedido_ja_gravado_nao_muda(conn, fab):
    """So o INSERT troca a loja: o que ja esta gravado (antes da fusao) fica como esta."""
    lj = lojas(conn)
    pedido = fab.pedido(loja=fab.loja(), cliente=fab.usuario("cliente"))
    conn.execute("UPDATE pedido SET id_loja = %s WHERE id_pedido = %s", (lj["site"], pedido))
    assert loja_do_pedido(conn, pedido) == lj["site"]


@pytest.fixture
def sa_conn(sa_conn):
    """O checkout faz commit; sem isto os dados do teste sobram e quebram os outros."""
    return SemCommit(sa_conn)


def test_checkout_no_app_da_vulto_vende_e_baixa_o_estoque_do_ecommerce(sa_conn, fab_sa):
    lj = lojas(fab_sa.conn)
    variacao = fab_sa.variacao()
    fab_sa.estoque(loja=lj["ecommerce"], variacao=variacao, quantidade=5)
    metodo = sa_conn.exec_driver_sql("SELECT codigo FROM metodo_pagamento LIMIT 1").scalar_one()
    pedido = repositorio.criar_checkout(
        sa_conn,
        fab_sa.usuario("cliente").id,
        {
            "id_loja": lj["app"],
            "entrega": "casa",
            "metodo_pagamento": metodo,
            "frete": Decimal("0.00"),
            "endereco_entrega": None,
            "itens": [{"id_variacao": variacao, "quantidade": 2}],
        },
    )
    assert str(pedido["id_loja"]) == str(lj["ecommerce"])
    assert (
        sa_conn.exec_driver_sql(
            "SELECT quantidade FROM estoque WHERE id_loja = %s AND id_variacao = %s",
            (lj["ecommerce"], variacao),
        ).scalar_one()
        == 3
    )
