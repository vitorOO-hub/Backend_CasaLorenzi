"""Cartao de cada loja (Gestao > Lojas) contra um Postgres real."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.gerencia import service
from app.gerencia.repositorio import Filtro

pytestmark = pytest.mark.banco


@pytest.fixture
def cena(fab_sa):
    fab = fab_sa
    c = fab.conn
    a, b = fab.loja(), fab.loja()
    cliente = fab.usuario("cliente")
    gerente_a = fab.usuario("gerente_loja", loja=a)
    fab.usuario("operador_estoque", loja=a)
    inativo = fab.usuario("atendente", loja=a, ativo=False)
    gerente_b = fab.usuario("gerente_loja", loja=b)

    def um(sql, p=()):
        return c.execute(sql, p).fetchone()[0]

    produto = um(
        "INSERT INTO produto (nome, marca, preco_base) "
        "VALUES ('Camisa L', 'C', 1) RETURNING id_produto"
    )

    def variacao(sku, ativa=True):
        return um(
            "INSERT INTO variacao_produto (id_produto, sku, cor, tamanho, preco_venda, ativa) "
            "VALUES (%s, %s, 'c', %s, 100, %s) RETURNING id_variacao",
            (produto, sku, sku, ativa),
        )

    v1, v2, v3 = variacao("L1"), variacao("L2"), variacao("L3", ativa=False)
    for loja, var, qtd, minimo in ((a, v1, 5, 2), (a, v2, 1, 2), (a, v3, 0, 3), (b, v1, 9, 2)):
        c.execute(
            "INSERT INTO estoque (id_loja, id_variacao, quantidade, estoque_minimo) "
            "VALUES (%s, %s, %s, %s)",
            (loja, var, qtd, minimo),
        )
    agora = datetime.now(UTC)

    def venda(loja, quantidade, dias_atras, status="pago"):
        pedido = um(
            "INSERT INTO pedido (numero_pedido, id_loja, id_cliente, id_status_pedido, criado_em) "
            "VALUES (%s, %s, %s, "
            "(SELECT id_status_pedido FROM status_pedido WHERE codigo = %s), %s) "
            "RETURNING id_pedido",
            (f"LJ-{fab._proximo()}", loja, cliente.id, status, agora - timedelta(days=dias_atras)),
        )
        c.execute(
            "INSERT INTO item_pedido (id_pedido, id_variacao, quantidade, preco_unitario) "
            "VALUES (%s, %s, %s, 100)",
            (pedido, v1, quantidade),
        )

    venda(a, 2, 5)  # 200 dentro dos 30 dias
    venda(a, 1, 40)  # fora da janela
    venda(a, 3, 2, status="cancelado")  # cancelado nao conta
    venda(b, 4, 1)
    fab.atendimento(cliente=cliente, loja=a)  # aberto
    fab.atendimento(cliente=cliente, loja=a, status="resolvido")
    fab.atendimento(cliente=cliente, loja=b)
    return SimpleNamespace(a=a, b=b, gerente_a=gerente_a, gerente_b=gerente_b, inativo=inativo)


def cartao(conn, loja):
    itens = service.montar_lojas(conn, Filtro(loja))["itens"]
    return {i["id_loja"]: i for i in itens}


def test_cartao_da_loja_traz_so_numeros_da_propria_loja(sa_conn, cena):
    r = cartao(sa_conn, cena.a)
    assert set(r) == {cena.a}
    a = r[cena.a]
    assert a["equipe"] == 2  # gerente e operador; o atendente inativo nao conta
    assert a["unidades_em_estoque"] == 6
    assert a["pecas_em_alerta"] == 1  # so a ativa abaixo do minimo (L2); L3 e inativa
    assert a["vendas_30_dias"] == 200.0
    assert a["chamados_abertos"] == 1
    assert a["gerente"].startswith("Usuario")


def test_admin_ve_a_rede_e_cada_loja_tem_o_seu_numero(sa_conn, cena):
    r = cartao(sa_conn, None)
    assert {cena.a, cena.b} <= set(r)
    assert r[cena.b]["vendas_30_dias"] == 400.0 and r[cena.b]["unidades_em_estoque"] == 9
    assert r[cena.b]["chamados_abertos"] == 1 and r[cena.b]["pecas_em_alerta"] == 0
