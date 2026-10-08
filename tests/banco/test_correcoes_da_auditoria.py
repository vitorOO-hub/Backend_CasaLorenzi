"""Correcoes da auditoria contra um Postgres real: frete do checkout e conta excluida no Auth."""

import json
from decimal import Decimal

import pytest

from app.cliente import repositorio
from tests.banco.test_chat_repositorio import SemCommit

pytestmark = pytest.mark.banco


@pytest.fixture
def sa_conn(sa_conn):
    """O checkout faz commit; sem isto os dados do teste sobram e quebram os outros."""
    return SemCommit(sa_conn)


def test_checkout_grava_frete_canal_e_total_que_fecha_com_os_itens(sa_conn, fab_sa):
    cliente = fab_sa.usuario("cliente")
    loja = fab_sa.loja()
    variacao = fab_sa.variacao()
    fab_sa.estoque(loja=loja, variacao=variacao, quantidade=5)
    metodo = sa_conn.exec_driver_sql("SELECT codigo FROM metodo_pagamento LIMIT 1").scalar_one()
    preco = sa_conn.exec_driver_sql(
        "SELECT preco_venda FROM variacao_produto WHERE id_variacao = %s", (variacao,)
    ).scalar_one()

    pedido = repositorio.criar_checkout(
        sa_conn,
        cliente.id,
        {
            "id_loja": loja,
            "entrega": "casa",
            "metodo_pagamento": metodo,
            "frete": Decimal("49.00"),
            "endereco_entrega": None,
            "itens": [{"id_variacao": variacao, "quantidade": 2}],
        },
        chave_idempotencia="chave-da-auditoria",
    )
    linha = sa_conn.exec_driver_sql(
        "SELECT valor_total, valor_frete, canal_venda FROM pedido WHERE id_pedido = %s",
        (pedido["id_pedido"],),
    ).one()
    assert linha.valor_frete == Decimal("49.00") and linha.canal_venda == "online"
    assert linha.valor_total == Decimal(preco) * 2 + Decimal("49.00")

    # Repetir a mesma chave devolve o mesmo pedido e nao baixa o estoque de novo.
    de_novo = repositorio.criar_checkout(
        sa_conn,
        cliente.id,
        {
            "id_loja": loja,
            "entrega": "casa",
            "metodo_pagamento": metodo,
            "frete": Decimal("49.00"),
            "endereco_entrega": None,
            "itens": [{"id_variacao": variacao, "quantidade": 2}],
        },
        chave_idempotencia="chave-da-auditoria",
    )
    assert de_novo["id_pedido"] == pedido["id_pedido"]
    saldo = sa_conn.exec_driver_sql(
        "SELECT quantidade FROM estoque WHERE id_loja = %s AND id_variacao = %s", (loja, variacao)
    ).scalar_one()
    assert saldo == 3


def test_excluir_a_conta_no_auth_desativa_o_usuario_e_solta_o_vinculo(conn):
    meta = {
        "cadastro_cliente": "true",
        "nome": "Helena Souza",
        "telefone": "11999990001",
        "rua": "Rua A",
        "bairro": "Centro",
        "numero_endereco": "1",
        "cep": "01001000",
    }
    auth = conn.execute(
        "INSERT INTO auth.users (email, raw_user_meta_data) VALUES (%s, %s::jsonb) RETURNING id",
        ("excluida@exemplo.com", json.dumps(meta)),
    ).fetchone()[0]
    antes = conn.execute(
        "SELECT ativo, auth_user_id FROM usuario WHERE email = 'excluida@exemplo.com'"
    ).fetchone()
    assert antes == (True, auth)

    conn.execute("DELETE FROM auth.users WHERE id = %s", (auth,))
    depois = conn.execute(
        "SELECT ativo, auth_user_id FROM usuario WHERE email = 'excluida@exemplo.com'"
    ).fetchone()
    assert depois == (False, None)  # a linha fica (pedidos e chamados), mas sem acesso
