"""Carrinho do cliente contra um Postgres real: o subtotal sai certo e cada cliente ve so o seu."""

from decimal import Decimal

import pytest

from app.cliente import repositorio

pytestmark = pytest.mark.banco


def id_do_cliente(conn, usuario):
    return conn.exec_driver_sql(
        "SELECT id_usuario FROM usuario WHERE auth_user_id = %s", (usuario.auth,)
    ).scalar_one()


def test_subtotal_do_carrinho_e_isolamento_entre_clientes(sa_conn, fab_sa):
    a, b = fab_sa.usuario("cliente"), fab_sa.usuario("cliente")
    variacao = fab_sa.variacao()
    id_a, id_b = id_do_cliente(sa_conn, a), id_do_cliente(sa_conn, b)
    preco = sa_conn.exec_driver_sql(
        "SELECT preco_venda FROM variacao_produto WHERE id_variacao = %s", (variacao,)
    ).scalar_one()

    # Regressao: o subtotal quebrava (500) porque o valor ja vinha como texto.
    repositorio.adicionar_item_carrinho(sa_conn, id_a, id_variacao=variacao, quantidade=2)
    carrinho = repositorio.adicionar_item_carrinho(
        sa_conn, id_a, id_variacao=variacao, quantidade=1
    )
    assert [i["quantidade"] for i in carrinho["itens"]] == [3]
    assert Decimal(carrinho["subtotal"]) == (Decimal(preco) * 3).quantize(Decimal("0.01"))
    assert repositorio.obter_carrinho(sa_conn, id_a) == carrinho

    assert repositorio.obter_carrinho(sa_conn, id_b) == {"itens": [], "subtotal": "0.00"}

    # O checkout abre com o endereco do cadastro; a conta da fabrica ja tem um completo.
    perfil = repositorio.perfil_cliente(sa_conn, id_a)
    assert (perfil["rua"], perfil["bairro"], perfil["numero_endereco"], perfil["cep"]) == (
        "Rua Teste",
        "Centro",
        "10",
        "01001000",
    )
    assert perfil["complemento"] is None
