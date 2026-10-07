"""Saldo e historico de movimentacoes contra um Postgres real."""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.erros_auth import SemPermissao
from app.core.papeis import Papel, UsuarioAtual
from app.dashboard.erros import PeriodoInvalido
from app.painel_estoque import repositorio, service
from app.painel_estoque.repositorio import FiltroMovimentacoes, FiltroSaldo

pytestmark = pytest.mark.banco

BRT = timezone(timedelta(hours=-3))
SINAL = {
    "entrada": 1,
    "cancelamento_venda": 1,
    "ajuste_positivo": 1,
    "transferencia_entrada": 1,
    "saida": -1,
    "venda": -1,
    "ajuste_negativo": -1,
    "transferencia_saida": -1,
}


def em(dia, hora=12, minuto=0, mes=9):
    return datetime(2026, mes, dia, hora, minuto, tzinfo=BRT)


class Cena:
    def __init__(self, fab):
        self.fab = fab
        self.c = fab.conn
        self.saldo = {}

    def _um(self, comando, parametros=()):
        return self.c.execute(comando, parametros).fetchone()[0]

    def produto(self, nome, categoria="Camisas", ativo=True):
        return self._um(
            "INSERT INTO produto (nome, marca, categoria, preco_base, ativo) "
            "VALUES (%s, 'Casa Lorenzi', %s, 100, %s) RETURNING id_produto",
            (nome, categoria, ativo),
        )

    def variacao(self, id_produto, sku, preco=100, ativa=True, cor="Branco", tamanho=None):
        return self._um(
            "INSERT INTO variacao_produto (id_produto, sku, cor, tamanho, preco_venda, ativa) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id_variacao",
            (id_produto, sku, cor, tamanho or sku, preco, ativa),
        )

    def estoque(self, loja, variacao, quantidade, minimo=0):
        self.saldo[(loja, variacao)] = quantidade
        self.c.execute(
            "INSERT INTO estoque (id_loja, id_variacao, quantidade, estoque_minimo) "
            "VALUES (%s, %s, %s, %s)",
            (loja, variacao, quantidade, minimo),
        )

    def movimento(
        self, loja, variacao, tipo, quantidade, quando, *, usuario=None, motivo=None, pedido=None
    ):
        anterior = self.saldo.get((loja, variacao), 100)
        posterior = anterior + SINAL[tipo] * quantidade
        self.saldo[(loja, variacao)] = posterior
        return self._um(
            """
            INSERT INTO movimentacao_estoque (
                id_loja, id_variacao, id_pedido, id_usuario_responsavel,
                id_tipo_movimentacao_estoque, quantidade, quantidade_anterior,
                quantidade_posterior, motivo, criada_em)
            VALUES (%s, %s, %s, %s,
                    (SELECT id_tipo_movimentacao_estoque FROM tipo_movimentacao_estoque
                     WHERE codigo = %s),
                    %s, %s, %s, %s, %s)
            RETURNING id_movimentacao_estoque
            """,
            (
                loja,
                variacao,
                pedido,
                usuario.id if usuario else None,
                tipo,
                quantidade,
                anterior,
                posterior,
                motivo,
                quando,
            ),
        )


@pytest.fixture
def cena(fab_sa):
    fab = fab_sa
    c = Cena(fab)
    loja_a, loja_b = fab.loja(), fab.loja()
    camisa, calca = c.produto("Camisa Linho", "Camisas"), c.produto("Calca Torino", "Calcas")
    v = SimpleNamespace(
        ok=c.variacao(camisa, "SKU-OK", 100),
        baixo=c.variacao(camisa, "SKU-BAIXO", 200),
        esgotado=c.variacao(calca, "SKU-ESGOTADO", 300),
        so_b=c.variacao(calca, "SKU-SO-B", 50),
    )
    c.estoque(loja_a, v.ok, 20, 5)
    c.estoque(loja_a, v.baixo, 5, 5)  # no minimo: conta como baixo
    c.estoque(loja_a, v.esgotado, 0, 3)
    c.estoque(loja_b, v.ok, 7, 5)
    c.estoque(loja_b, v.so_b, 9, 2)
    return SimpleNamespace(
        c=c,
        fab=fab,
        a=loja_a,
        b=loja_b,
        v=v,
        camisa=camisa,
        calca=calca,
        gerente=fab.usuario("gerente_loja", loja=loja_a),
        operador=fab.usuario("operador_estoque", loja=loja_a),
        outro_operador=fab.usuario("operador_estoque", loja=loja_a),
        cliente=fab.usuario("cliente"),
    )


def saldo(conn, filtro, limit=50, offset=0):
    return service.montar_saldo(conn, filtro, limit=limit, offset=offset)


def skus(resultado):
    return [i["sku"] for i in resultado["itens"]]


# ------------------------------------------------------------------ saldo


def test_a_loja_ve_so_as_pecas_que_mantem_em_estoque(sa_conn, cena):
    assert set(skus(saldo(sa_conn, FiltroSaldo(cena.a)))) == {"SKU-OK", "SKU-BAIXO", "SKU-ESGOTADO"}
    assert set(skus(saldo(sa_conn, FiltroSaldo(cena.b)))) == {"SKU-OK", "SKU-SO-B"}


def test_a_rede_soma_as_lojas_e_traz_o_saldo_de_cada_uma(sa_conn, cena):
    r = saldo(sa_conn, FiltroSaldo(None))
    ok = next(i for i in r["itens"] if i["sku"] == "SKU-OK")
    assert (ok["total"], ok["minimo_total"]) == (27, 10)
    assert {(p["id_loja"], p["quantidade"], p["minimo"]) for p in ok["por_loja"]} == {
        (cena.a, 20, 5),
        (cena.b, 7, 5),
    }
    assert {x["id_loja"] for x in r["lojas"]} >= {cena.a, cena.b}


def test_com_loja_so_o_saldo_dela_aparece(sa_conn, cena):
    ok = next(i for i in saldo(sa_conn, FiltroSaldo(cena.a))["itens"] if i["sku"] == "SKU-OK")
    assert ok["total"] == 20 and [p["id_loja"] for p in ok["por_loja"]] == [cena.a]


@pytest.mark.parametrize(
    ("sku", "situacao"), [("SKU-OK", "ok"), ("SKU-BAIXO", "baixo"), ("SKU-ESGOTADO", "esgotado")]
)
def test_situacao_de_cada_peca(sa_conn, cena, sku, situacao):
    item = next(i for i in saldo(sa_conn, FiltroSaldo(cena.a))["itens"] if i["sku"] == sku)
    assert item["situacao"] == situacao


def test_resumo_conta_unidades_situacoes_e_valor(sa_conn, cena):
    r = saldo(sa_conn, FiltroSaldo(cena.a))["resumo"]
    assert r == {
        "unidades": 25,
        "pecas": 3,
        "estoque_baixo": 1,
        "esgotadas": 1,
        "valor_em_estoque": 20 * 100 + 5 * 200,  # a preco de venda
    }


def test_resumo_nao_muda_com_os_filtros_da_tela(sa_conn, cena):
    todos = saldo(sa_conn, FiltroSaldo(cena.a))["resumo"]
    filtrado = saldo(sa_conn, FiltroSaldo(cena.a, busca="linho", situacao="ok"))
    assert filtrado["resumo"] == todos and filtrado["total"] == 1


def test_busca_por_nome_ou_sku_sem_diferenciar_maiusculas(sa_conn, cena):
    assert skus(saldo(sa_conn, FiltroSaldo(cena.a, busca="CALCA"))) == ["SKU-ESGOTADO"]
    assert skus(saldo(sa_conn, FiltroSaldo(cena.a, busca="sku-baixo"))) == ["SKU-BAIXO"]
    assert skus(saldo(sa_conn, FiltroSaldo(cena.a, busca="inexistente"))) == []


@pytest.mark.parametrize("busca", ["%", "_", "%%", "' OR '1'='1", "SKU-%"])
def test_texto_da_busca_nunca_vira_curinga_nem_sql(sa_conn, cena, busca):
    assert saldo(sa_conn, FiltroSaldo(cena.a, busca=busca))["itens"] == []


def test_filtro_de_categoria_e_de_situacao(sa_conn, cena):
    assert set(skus(saldo(sa_conn, FiltroSaldo(cena.a, categoria="Camisas")))) == {
        "SKU-OK",
        "SKU-BAIXO",
    }
    assert skus(saldo(sa_conn, FiltroSaldo(cena.a, situacao="esgotado"))) == ["SKU-ESGOTADO"]
    assert skus(saldo(sa_conn, FiltroSaldo(cena.a, categoria="Calcas", situacao="ok"))) == []


def test_peca_ou_produto_inativo_nao_aparece(sa_conn, cena):
    inativa = cena.c.variacao(cena.camisa, "SKU-INATIVA", ativa=False)
    fora = cena.c.variacao(cena.c.produto("Fora de linha", ativo=False), "SKU-FORA")
    cena.c.estoque(cena.a, inativa, 5)
    cena.c.estoque(cena.a, fora, 5)
    r = saldo(sa_conn, FiltroSaldo(cena.a))
    assert "SKU-INATIVA" not in skus(r) and "SKU-FORA" not in skus(r)
    assert r["resumo"]["pecas"] == 3


def test_paginacao_devolve_o_total_real(sa_conn, cena):
    primeira = saldo(sa_conn, FiltroSaldo(cena.a), limit=2, offset=0)
    segunda = saldo(sa_conn, FiltroSaldo(cena.a), limit=2, offset=2)
    assert primeira["total"] == segunda["total"] == 3
    assert len(primeira["itens"]) == 2 and len(segunda["itens"]) == 1
    assert not set(skus(primeira)) & set(skus(segunda))


def test_preco_e_o_de_venda_da_variacao(sa_conn, cena):
    item = next(i for i in saldo(sa_conn, FiltroSaldo(cena.a))["itens"] if i["sku"] == "SKU-BAIXO")
    assert item["preco"] == 200.0 and item["cor"] == "Branco"


def test_opcoes_trazem_categorias_pecas_e_escopo(sa_conn, cena):
    usuario = UsuarioAtual(id_auth=cena.gerente.auth, papel=Papel.GERENTE_LOJA, id_loja=cena.a)
    o = service.montar_opcoes(sa_conn, usuario, cena.a)
    assert o["categorias"] == ["Calcas", "Camisas"]
    assert {p["sku"] for p in o["pecas"]} == {"SKU-OK", "SKU-BAIXO", "SKU-ESGOTADO"}
    assert [x["id_loja"] for x in o["lojas"]] == [cena.a]
    assert {cena.a, cena.b} <= {x["id_loja"] for x in o["rede"]}  # a rede toda, so id e nome
    assert o["escopo"]["somente_minhas"] is False and o["escopo"]["pode_escolher_loja"] is False
    assert {t["codigo"] for t in o["tipos"]} == {"entrada", "saida", "ajuste", "transferencia"}
    operador = UsuarioAtual(
        id_auth=cena.operador.auth, papel=Papel.OPERADOR_ESTOQUE, id_loja=cena.a
    )
    assert service.montar_opcoes(sa_conn, operador, cena.a)["escopo"]["somente_minhas"] is True


# ------------------------------------------------------------------ movimentacoes


def historico(conn, filtro, limit=100, offset=0):
    return service.montar_movimentacoes(conn, filtro, limit=limit, offset=offset)


def test_quantidade_vem_com_sinal_e_grupo_de_cada_tipo(sa_conn, cena):
    c, a, v = cena.c, cena.a, cena.v.ok
    pedido = cena.fab.pedido(loja=a, cliente=cena.cliente)
    esperado = {
        "entrada": (5, "entrada", 5),
        "cancelamento_venda": (2, "entrada", 2),
        "ajuste_positivo": (1, "ajuste", 1),
        "ajuste_negativo": (3, "ajuste", -3),
        "saida": (4, "saida", -4),
        "venda": (2, "saida", -2),
        "transferencia_entrada": (6, "transferencia", 6),
        "transferencia_saida": (7, "transferencia", -7),
    }
    for tipo, (quantidade, _g, _s) in esperado.items():
        precisa_pedido = tipo in ("venda", "cancelamento_venda")
        c.movimento(a, v, tipo, quantidade, em(10), pedido=pedido if precisa_pedido else None)
    r = historico(sa_conn, FiltroMovimentacoes(a))
    por_tipo = {i["tipo_codigo"]: i for i in r["itens"]}
    assert set(por_tipo) == set(esperado)
    for tipo, (_q, grupo, assinada) in esperado.items():
        assert (por_tipo[tipo]["grupo"], por_tipo[tipo]["quantidade"]) == (grupo, assinada)


def test_filtro_por_grupo(sa_conn, cena):
    c, a, v = cena.c, cena.a, cena.v.ok
    c.movimento(a, v, "entrada", 5, em(1))
    c.movimento(a, v, "saida", 1, em(2))
    c.movimento(a, v, "ajuste_negativo", 1, em(3))
    c.movimento(a, v, "transferencia_saida", 1, em(4))
    pedido = cena.fab.pedido(loja=a, cliente=cena.cliente)
    c.movimento(a, v, "venda", 1, em(5), pedido=pedido)
    grupos = {
        g: historico(sa_conn, FiltroMovimentacoes(a, grupo=g))["total"]
        for g, _ in repositorio.GRUPOS
    }
    assert grupos == {"entrada": 1, "saida": 2, "ajuste": 1, "transferencia": 1}  # venda e saida


def test_so_a_loja_do_escopo_e_a_rede_para_o_admin(sa_conn, cena):
    cena.c.movimento(cena.a, cena.v.ok, "entrada", 1, em(1))
    cena.c.movimento(cena.b, cena.v.ok, "entrada", 1, em(2))
    assert {i["id_loja"] for i in historico(sa_conn, FiltroMovimentacoes(cena.a))["itens"]} == {
        cena.a
    }
    assert historico(sa_conn, FiltroMovimentacoes(None))["total"] == 2


def test_ordem_da_mais_recente_para_a_mais_antiga_com_total_e_pagina(sa_conn, cena):
    for dia in (3, 1, 2):
        cena.c.movimento(cena.a, cena.v.ok, "entrada", dia, em(dia))
    r = historico(sa_conn, FiltroMovimentacoes(cena.a))
    assert [i["quantidade"] for i in r["itens"]] == [3, 2, 1]
    pagina = historico(sa_conn, FiltroMovimentacoes(cena.a), limit=1, offset=1)
    assert pagina["total"] == 3 and [i["quantidade"] for i in pagina["itens"]] == [2]


def test_filtro_por_sku(sa_conn, cena):
    cena.c.movimento(cena.a, cena.v.ok, "entrada", 1, em(1))
    cena.c.movimento(cena.a, cena.v.baixo, "entrada", 1, em(2))
    r = historico(sa_conn, FiltroMovimentacoes(cena.a, sku="SKU-BAIXO"))
    assert [i["sku"] for i in r["itens"]] == ["SKU-BAIXO"]


def test_periodo_usa_o_dia_de_sao_paulo_nas_duas_pontas(sa_conn, cena):
    c, a, v = cena.c, cena.a, cena.v.ok
    c.movimento(a, v, "entrada", 1, em(31, 23, 59, mes=8))  # antes
    c.movimento(a, v, "entrada", 2, em(1, 0, 0))  # primeiro instante
    c.movimento(a, v, "entrada", 3, em(30, 23, 30))  # ultimo dia, noite
    c.movimento(a, v, "entrada", 4, em(1, 0, 30, mes=10))  # depois
    r = historico(sa_conn, FiltroMovimentacoes(a, de=date(2026, 9, 1), ate=date(2026, 9, 30)))
    assert sorted(i["quantidade"] for i in r["itens"]) == [2, 3]
    so_de = historico(sa_conn, FiltroMovimentacoes(a, de=date(2026, 9, 30)))
    assert sorted(i["quantidade"] for i in so_de["itens"]) == [3, 4]
    so_ate = historico(sa_conn, FiltroMovimentacoes(a, ate=date(2026, 9, 1)))
    assert sorted(i["quantidade"] for i in so_ate["itens"]) == [1, 2]


def test_mostra_responsavel_motivo_pedido_e_saldos(sa_conn, cena):
    pedido = cena.c._um(
        "INSERT INTO pedido (numero_pedido, id_loja, id_cliente, id_status_pedido) VALUES "
        "('SD-777', %s, %s, (SELECT id_status_pedido FROM status_pedido WHERE codigo = 'pago')) "
        "RETURNING id_pedido",
        (cena.a, cena.cliente.id),
    )
    cena.c.saldo[(cena.a, cena.v.ok)] = 20
    cena.c.movimento(cena.a, cena.v.ok, "venda", 2, em(10), pedido=pedido, motivo="Pedido SD-777")
    cena.c.movimento(
        cena.a, cena.v.ok, "entrada", 5, em(11), usuario=cena.operador, motivo="Fornecedor"
    )
    r = {i["tipo_codigo"]: i for i in historico(sa_conn, FiltroMovimentacoes(cena.a))["itens"]}
    assert (r["venda"]["responsavel"], r["venda"]["numero_pedido"]) == (None, "SD-777")
    assert (r["venda"]["quantidade_anterior"], r["venda"]["quantidade_posterior"]) == (20, 18)
    assert r["entrada"]["responsavel"].startswith("Usuario")  # nome de quem registrou
    assert r["entrada"]["motivo"] == "Fornecedor" and r["entrada"]["numero_pedido"] is None
    assert r["entrada"]["produto"] == "Camisa Linho"


def test_operador_ve_so_o_que_ele_registrou(sa_conn, cena):
    c, a, v = cena.c, cena.a, cena.v.ok
    c.movimento(a, v, "entrada", 1, em(1), usuario=cena.operador)
    c.movimento(a, v, "entrada", 2, em(2), usuario=cena.outro_operador)
    c.movimento(a, v, "entrada", 3, em(3), usuario=cena.gerente)
    c.movimento(a, v, "entrada", 4, em(4))
    operador = UsuarioAtual(id_auth=cena.operador.auth, papel=Papel.OPERADOR_ESTOQUE, id_loja=a)
    filtro = service.filtro_de_movimentacoes(
        sa_conn, operador, id_loja=a, grupo=None, sku=None, de=None, ate=None
    )
    assert [i["quantidade"] for i in historico(sa_conn, filtro)["itens"]] == [1]
    gerente = UsuarioAtual(id_auth=cena.gerente.auth, papel=Papel.GERENTE_LOJA, id_loja=a)
    filtro = service.filtro_de_movimentacoes(
        sa_conn, gerente, id_loja=a, grupo=None, sku=None, de=None, ate=None
    )
    assert historico(sa_conn, filtro)["total"] == 4  # a gestao ve tudo da loja


def test_operador_sem_cadastro_ativo_e_recusado(sa_conn, cena):
    fantasma = UsuarioAtual(id_auth=uuid4(), papel=Papel.OPERADOR_ESTOQUE, id_loja=cena.a)
    with pytest.raises(SemPermissao):
        service.filtro_de_movimentacoes(
            sa_conn, fantasma, id_loja=cena.a, grupo=None, sku=None, de=None, ate=None
        )


def test_periodo_invertido_e_recusado(sa_conn, cena):
    gerente = UsuarioAtual(id_auth=cena.gerente.auth, papel=Papel.GERENTE_LOJA, id_loja=cena.a)
    with pytest.raises(PeriodoInvalido):
        service.filtro_de_movimentacoes(
            sa_conn,
            gerente,
            id_loja=cena.a,
            grupo=None,
            sku=None,
            de=date(2026, 9, 30),
            ate=date(2026, 9, 1),
        )


def test_escopo_de_loja_do_service(cena):
    gerente = UsuarioAtual(id_auth=cena.gerente.auth, papel=Papel.GERENTE_LOJA, id_loja=cena.a)
    assert service.loja_do_escopo(gerente, None) == cena.a
    with pytest.raises(SemPermissao):
        service.loja_do_escopo(gerente, cena.b)
    atendente = UsuarioAtual(id_auth=uuid4(), papel=Papel.ATENDENTE, id_loja=cena.a)
    with pytest.raises(SemPermissao):
        service.loja_do_escopo(atendente, None)
    admin = UsuarioAtual(id_auth=uuid4(), papel=Papel.ADMIN, id_loja=None)
    assert service.loja_do_escopo(admin, None) is None
    assert service.loja_do_escopo(admin, cena.b) == cena.b
