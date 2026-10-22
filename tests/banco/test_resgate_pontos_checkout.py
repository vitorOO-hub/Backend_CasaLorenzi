"""Resgate de pontos Lorenzi+ no checkout, contra um Postgres real: R$ 5 a cada 100 pontos, so nas
pecas, com saldo suficiente; compra cancelada devolve os pontos."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.cliente import repositorio
from app.cliente.erros import PontosInsuficientes, ResgateAcimaDoValor
from app.cliente.schemas import CheckoutCriacao
from tests.banco.test_chat_repositorio import SemCommit

pytestmark = pytest.mark.banco


@pytest.fixture
def sa_conn(sa_conn):
    """O checkout faz commit; sem isto os dados do teste sobram e quebram os outros."""
    return SemCommit(sa_conn)


@pytest.fixture
def cena(sa_conn, fab_sa):
    cliente = fab_sa.usuario("cliente")
    loja = fab_sa.loja()
    variacao = fab_sa.variacao()
    fab_sa.conn.execute(
        "UPDATE variacao_produto SET preco_venda = 200 WHERE id_variacao = %s", (variacao,)
    )
    fab_sa.estoque(loja=loja, variacao=variacao, quantidade=5)
    fab_sa.conn.execute(
        "INSERT INTO movimento_pontos (id_usuario, tipo, pontos, ocorrido_em, vence_em, descricao)"
        " VALUES (%s, 'credito', 1000, now() - interval '10 days',"
        " now() + interval '355 days', 'compra antiga')",
        (cliente.id,),
    )
    metodo = sa_conn.exec_driver_sql("SELECT codigo FROM metodo_pagamento LIMIT 1").scalar_one()
    return cliente, loja, variacao, metodo


def comprar(sa_conn, cena, pontos):
    cliente, loja, variacao, metodo = cena
    return repositorio.criar_checkout(
        sa_conn,
        cliente.id,
        {
            "id_loja": loja,
            "entrega": "casa",
            "metodo_pagamento": metodo,
            "frete": Decimal("30.00"),
            "endereco_entrega": None,
            "itens": [{"id_variacao": variacao, "quantidade": 2}],
            "pontos_resgatados": pontos,
        },
    )


def saldo(sa_conn, cliente):
    return sa_conn.exec_driver_sql(
        "SELECT COALESCE(sum(pontos), 0) FROM movimento_pontos WHERE id_usuario = %s",
        (cliente.id,),
    ).scalar_one()


def test_resgate_vira_desconto_nas_pecas_e_a_compra_rende_sobre_o_que_foi_pago(sa_conn, cena):
    cliente = cena[0]
    pedido = comprar(sa_conn, cena, 400)  # 400 pontos = R$ 20
    total = sa_conn.exec_driver_sql(
        "SELECT valor_total FROM pedido WHERE id_pedido = %s", (pedido["id_pedido"],)
    ).scalar_one()
    assert total == Decimal("410.00")  # 2 x 200 - 20 + 30 de frete
    resgate = sa_conn.exec_driver_sql(
        "SELECT pontos, desconto, id_pedido FROM resgate_pontos WHERE id_usuario = %s",
        (cliente.id,),
    ).one()
    assert (resgate.pontos, resgate.desconto, str(resgate.id_pedido)) == (
        400,
        Decimal("20.00"),
        str(pedido["id_pedido"]),
    )
    # 1000 - 400 resgatados + 820 da compra (R$ 410 no site, em dobro, frete incluso).
    assert saldo(sa_conn, cliente) == 1420


def test_saldo_insuficiente(sa_conn, cena):
    with pytest.raises(PontosInsuficientes):
        comprar(sa_conn, cena, 1100)


def test_desconto_nao_passa_do_valor_das_pecas(sa_conn, cena, fab_sa):
    fab_sa.conn.execute(
        "INSERT INTO movimento_pontos (id_usuario, tipo, pontos, ocorrido_em, descricao)"
        " VALUES (%s, 'ajuste', 20000, now(), 'bonus')",
        (cena[0].id,),
    )
    with pytest.raises(ResgateAcimaDoValor):
        comprar(sa_conn, cena, 8100)  # R$ 405 > R$ 400 em pecas


def test_cancelar_devolve_os_pontos_uma_vez(sa_conn, cena):
    from app.cliente.repositorio import vulto_mais_cliente

    cliente = cena[0]
    pedido = comprar(sa_conn, cena, 400)
    for _ in range(2):
        sa_conn.exec_driver_sql(
            "UPDATE pedido SET id_status_pedido = (SELECT id_status_pedido FROM status_pedido"
            " WHERE codigo = 'cancelado') WHERE id_pedido = %s",
            (pedido["id_pedido"],),
        )
    assert saldo(sa_conn, cliente) == 1000
    obs = sa_conn.exec_driver_sql(
        "SELECT observacao FROM resgate_pontos WHERE id_pedido = %s", (pedido["id_pedido"],)
    ).scalar_one()
    assert "pontos devolvidos" in obs
    # A devolucao nao conta como credito do ano.
    assert vulto_mais_cliente(sa_conn, cliente.id)["creditos_no_ano"] == 1000


def test_regras_vem_no_lorenzi_mais(sa_conn, cena):
    from app.cliente.repositorio import vulto_mais_cliente

    r = vulto_mais_cliente(sa_conn, cena[0].id)["regras"]
    assert (r["reais_a_cada_100_pontos"], r["multiplo_de_resgate"]) == (Decimal("5"), 100)


@pytest.mark.parametrize("pontos", [50, 150, -100])
def test_so_multiplos_de_100(pontos):
    with pytest.raises(ValidationError):
        CheckoutCriacao(
            id_loja="6f1c3a52-6a4e-4c8e-9a39-0f1f2b6f2f10",
            entrega="loja",
            metodo_pagamento="pix",
            itens=[{"id_variacao": "6f1c3a52-6a4e-4c8e-9a39-0f1f2b6f2f11", "quantidade": 1}],
            pontos_resgatados=pontos,
        )
