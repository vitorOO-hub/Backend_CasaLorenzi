from types import SimpleNamespace

import pytest

from tests.banco.apoio import como, e_erro, tenta
from tests.banco.fabrica import Usuario

pytestmark = pytest.mark.banco


def como_usuario(conn, usuario: Usuario):
    papel = {"diretor": "admin"}.get(usuario.tipo, usuario.tipo)
    papel = None if papel == "cliente" else papel
    loja = None if papel in (None, "admin") else usuario.loja
    return como(conn, sub=usuario.auth, papel=papel, loja=loja)


def ids_visiveis(conn, usuario: Usuario, consulta: str) -> set:
    with como_usuario(conn, usuario):
        return {linha[0] for linha in conn.execute(consulta).fetchall()}


@pytest.fixture
def cenario(fab):
    loja_a, loja_b = fab.loja(), fab.loja()
    usuarios = {
        "cliente1": fab.usuario("cliente"),
        "cliente2": fab.usuario("cliente"),
        "atendente_a": fab.usuario("atendente", loja=loja_a),
        "gerente_a": fab.usuario("gerente_loja", loja=loja_a),
        "operador_a": fab.usuario("operador_estoque", loja=loja_a),
        "operador_b": fab.usuario("operador_estoque", loja=loja_b),
        "operador_a_inativo": fab.usuario("operador_estoque", loja=loja_a, ativo=False),
        "admin": fab.usuario("diretor"),
    }
    c1, c2 = usuarios["cliente1"], usuarios["cliente2"]
    pedidos = {
        "p1": fab.pedido(loja=loja_a, cliente=c1),
        "p2": fab.pedido(loja=loja_a, cliente=c2),
        "p3": fab.pedido(loja=loja_b, cliente=c1),
    }
    itens = {
        "i1": fab.item_pedido(pedido=pedidos["p1"]),
        "i2": fab.item_pedido(pedido=pedidos["p2"]),
    }
    pagamentos = {
        "g1": fab.pagamento(pedido=pedidos["p1"]),
        "g2": fab.pagamento(pedido=pedidos["p2"]),
    }
    estoques = {"e_a": fab.estoque(loja=loja_a), "e_b": fab.estoque(loja=loja_b)}
    movimentacoes = {"m_a": fab.movimentacao(loja=loja_a), "m_b": fab.movimentacao(loja=loja_b)}
    return SimpleNamespace(
        usuarios=usuarios,
        pedidos=pedidos,
        itens=itens,
        pagamentos=pagamentos,
        estoques=estoques,
        movimentacoes=movimentacoes,
    )


def esperados(mapa: dict, nomes: set) -> set:
    return {mapa[nome] for nome in nomes}


@pytest.mark.parametrize(
    ("quem", "nomes"),
    [
        ("cliente1", {"p1", "p3"}),
        ("cliente2", {"p2"}),
        ("atendente_a", {"p1", "p2"}),
        ("gerente_a", {"p1", "p2"}),
        ("operador_a", {"p1", "p2"}),
        ("operador_b", {"p3"}),
        ("operador_a_inativo", set()),
        ("admin", {"p1", "p2", "p3"}),
    ],
)
def test_visibilidade_dos_pedidos(conn, cenario, quem, nomes):
    visiveis = ids_visiveis(conn, cenario.usuarios[quem], "SELECT id_pedido FROM pedido")
    assert visiveis == esperados(cenario.pedidos, nomes)


@pytest.mark.parametrize(
    ("quem", "nomes"),
    [
        ("cliente1", {"i1"}),
        ("cliente2", {"i2"}),
        ("atendente_a", {"i1", "i2"}),
        ("operador_b", set()),
        ("admin", {"i1", "i2"}),
    ],
)
def test_itens_do_pedido_herdam_a_visibilidade_do_pedido(conn, cenario, quem, nomes):
    visiveis = ids_visiveis(conn, cenario.usuarios[quem], "SELECT id_item_pedido FROM item_pedido")
    assert visiveis == esperados(cenario.itens, nomes)


@pytest.mark.parametrize(
    ("quem", "nomes"),
    [
        ("cliente1", {"g1"}),
        ("cliente2", {"g2"}),
        ("gerente_a", {"g1", "g2"}),
        ("operador_b", set()),
        ("admin", {"g1", "g2"}),
    ],
)
def test_pagamentos_herdam_a_visibilidade_do_pedido(conn, cenario, quem, nomes):
    visiveis = ids_visiveis(conn, cenario.usuarios[quem], "SELECT id_pagamento FROM pagamento")
    assert visiveis == esperados(cenario.pagamentos, nomes)


@pytest.mark.parametrize(
    ("quem", "nomes"),
    [
        ("operador_a", {"e_a"}),
        ("gerente_a", {"e_a"}),
        ("operador_b", {"e_b"}),
        ("atendente_a", set()),
        ("cliente1", set()),
        ("operador_a_inativo", set()),
        ("admin", {"e_a", "e_b"}),
    ],
)
def test_visibilidade_do_estoque(conn, cenario, quem, nomes):
    visiveis = ids_visiveis(conn, cenario.usuarios[quem], "SELECT id_estoque FROM estoque")
    assert visiveis == esperados(cenario.estoques, nomes)


@pytest.mark.parametrize(
    ("quem", "nomes"),
    [
        ("operador_a", {"m_a"}),
        ("gerente_a", {"m_a"}),
        ("operador_b", {"m_b"}),
        ("atendente_a", set()),
        ("cliente1", set()),
        ("admin", {"m_a", "m_b"}),
    ],
)
def test_visibilidade_das_movimentacoes(conn, cenario, quem, nomes):
    visiveis = ids_visiveis(
        conn,
        cenario.usuarios[quem],
        "SELECT id_movimentacao_estoque FROM movimentacao_estoque",
    )
    assert visiveis == esperados(cenario.movimentacoes, nomes)


@pytest.mark.parametrize(
    "tabela",
    ["pedido", "item_pedido", "pagamento", "estoque", "movimentacao_estoque"],
)
def test_anon_nao_le_pedidos_nem_estoque(conn, cenario, tabela):
    with como(conn, role="anon"):
        assert e_erro(tenta(conn, f"SELECT 1 FROM {tabela} LIMIT 1"))


@pytest.mark.parametrize(
    "comando",
    [
        "INSERT INTO estoque (id_loja, id_variacao) VALUES (gen_random_uuid(), gen_random_uuid())",
        "UPDATE estoque SET quantidade = 999",
        "DELETE FROM pedido",
        "UPDATE pedido SET valor_total = 0",
        "DELETE FROM movimentacao_estoque",
    ],
)
def test_nao_ha_escrita_direta_em_pedidos_e_estoque(conn, cenario, comando):
    with como_usuario(conn, cenario.usuarios["admin"]):
        assert e_erro(tenta(conn, comando))


@pytest.mark.parametrize("tabela", ["status_pagamento", "tipo_movimentacao_estoque"])
def test_opcoes_de_pedido_so_para_logados(conn, cenario, tabela):
    consulta = f"SELECT 1 FROM {tabela}"
    with como_usuario(conn, cenario.usuarios["cliente1"]):
        assert len(tenta(conn, consulta)) > 0
    with como(conn, role="anon"):
        assert e_erro(tenta(conn, consulta))
