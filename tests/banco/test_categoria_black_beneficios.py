"""Categoria Black e benefícios do Lorenzi+ contra um Postgres real: categoria pelo ano, lista de
benefícios na resposta e frete grátis aplicado pelo back no checkout."""

from decimal import Decimal

import pytest

from app.cliente import repositorio
from tests.banco.test_chat_repositorio import SemCommit

pytestmark = pytest.mark.banco


@pytest.fixture
def sa_conn(sa_conn):
    """O checkout faz commit; sem isto os dados do teste sobram e quebram os outros."""
    return SemCommit(sa_conn)


def credito(c, cliente, pontos):
    c.execute(
        "INSERT INTO movimento_pontos (id_usuario, tipo, pontos, ocorrido_em, vence_em, descricao)"
        " VALUES (%s, 'credito', %s, now(), now() + interval '365 days', 'teste')",
        (cliente.id, pontos),
    )


@pytest.mark.parametrize(
    ("pontos", "categoria", "beneficios", "proxima"),
    [
        (1500, "bronze", [], "prata"),
        (2500, "prata", ["frete_600"], "ouro"),
        (6000, "ouro", ["frete_sempre", "acesso_antecipado"], "black"),
        (12000, "black", ["frete_sempre", "acesso_antecipado", "ajuste_cortesia"], None),
    ],
)
def test_lorenzi_mais_traz_categoria_e_beneficios(
    sa_conn, fab_sa, pontos, categoria, beneficios, proxima
):
    cliente = fab_sa.usuario("cliente")
    credito(fab_sa.conn, cliente, pontos)
    r = repositorio.vulto_mais_cliente(sa_conn, cliente.id)
    assert (r["categoria"], r["proxima_categoria"]) == (categoria, proxima)
    assert [b["codigo"] for b in r["beneficios"]] == beneficios
    if proxima:
        assert r["proximos_beneficios"], "mostra o que o cliente ganha ao subir"
    else:
        assert r["faltam_para_proxima"] is None and r["proximos_beneficios"] == []


def comprar(sa_conn, fab_sa, cliente, preco, quantidade=1):
    loja = fab_sa.loja()
    variacao = fab_sa.variacao()
    fab_sa.conn.execute(
        "UPDATE variacao_produto SET preco_venda = %s WHERE id_variacao = %s", (preco, variacao)
    )
    fab_sa.estoque(loja=loja, variacao=variacao, quantidade=10)
    metodo = sa_conn.exec_driver_sql("SELECT codigo FROM metodo_pagamento LIMIT 1").scalar_one()
    pedido = repositorio.criar_checkout(
        sa_conn,
        cliente.id,
        {
            "id_loja": loja,
            "entrega": "casa",
            "metodo_pagamento": metodo,
            "frete": Decimal("49.00"),
            "endereco_entrega": None,
            "itens": [{"id_variacao": variacao, "quantidade": quantidade}],
        },
    )
    return sa_conn.exec_driver_sql(
        "SELECT valor_frete, valor_total FROM pedido WHERE id_pedido = %s", (pedido["id_pedido"],)
    ).one()


@pytest.mark.parametrize(
    ("pontos", "preco", "frete"),
    [
        (0, 500, Decimal("49.00")),  # bronze: paga abaixo de R$ 1.000
        (2500, 500, Decimal("49.00")),  # prata: paga abaixo de R$ 600
        (2500, 600, Decimal("0.00")),  # prata: grátis a partir de R$ 600
        (6000, 100, Decimal("0.00")),  # ouro: sempre grátis
        (12000, 100, Decimal("0.00")),  # black: sempre grátis
    ],
)
def test_checkout_aplica_o_frete_gratis_da_categoria(sa_conn, fab_sa, pontos, preco, frete):
    cliente = fab_sa.usuario("cliente")
    if pontos:
        credito(fab_sa.conn, cliente, pontos)
    linha = comprar(sa_conn, fab_sa, cliente, preco)
    assert linha.valor_frete == frete
    assert linha.valor_total == Decimal(preco) + frete
