# ruff: noqa: F811
"""Inicio do admin (rede e comparacao de lojas) contra um Postgres real: so os casos criticos."""

import pytest

from app.core.erros_auth import SemPermissao
from app.core.papeis import Papel
from app.gerencia import service
from tests.banco.test_gerencia_repositorio import FIM, INICIO, cena, em, usuario  # noqa: F401

pytestmark = pytest.mark.banco


def rede(conn, cena, *lojas, papel=Papel.ADMIN, **filtros):
    return service.montar_rede(
        conn,
        usuario(cena, papel),
        inicio=INICIO,
        fim=FIM,
        ids_loja=tuple(lojas),
        categoria=filtros.get("categoria"),
        canal=filtros.get("canal"),
    )


def venda(cena, loja, quantidade=1, **kw):
    cena.c.pedido(loja, cena.cliente, [(cena.cam_p, quantidade, 100)], **kw)


def linha(d, loja):
    return next(u for u in d["unidades"] if str(u["id_loja"]) == str(loja))


def test_so_o_admin_ve_a_rede(sa_conn, cena):
    for papel in (Papel.GERENTE_LOJA, Papel.ATENDENTE, Papel.OPERADOR_ESTOQUE):
        with pytest.raises(SemPermissao):
            rede(sa_conn, cena, papel=papel)


def test_rede_toda_soma_as_lojas_e_o_total_bate_com_a_tabela(sa_conn, cena):
    venda(cena, cena.loja_a, 2, quando=em(10))
    venda(cena, cena.loja_b, 3, canal="online", quando=em(11))
    venda(cena, cena.loja_b, 1, status="cancelado", quando=em(11))  # nao e venda
    d = rede(sa_conn, cena)
    assert [g["id"] for g in d["grupos"]] == ["rede"]
    assert (d["atual"]["pedidos"], d["atual"]["faturamento"]) == (2, 500.0)
    a, b = linha(d, cena.loja_a), linha(d, cena.loja_b)
    assert (a["faturamento"], b["faturamento"]) == (200.0, 300.0)
    assert b["participacao_online"] == 1.0 and a["participacao_online"] == 0.0
    assert a["ticket_medio"] == 200.0
    # A serie diaria da rede fecha com o faturamento do periodo.
    assert sum(p["faturamento"] for p in d["grupos"][0]["serie_diaria"]) == 500.0


def test_comparar_lojas_isola_cada_uma_e_deixa_as_outras_de_fora(sa_conn, cena):
    venda(cena, cena.loja_a, 2, quando=em(10))
    venda(cena, cena.loja_b, 3, quando=em(11))
    so_a = rede(sa_conn, cena, cena.loja_a)
    assert [g["id"] for g in so_a["grupos"]] == [str(cena.loja_a)]
    assert so_a["atual"]["faturamento"] == 200.0
    assert [str(u["id_loja"]) for u in so_a["unidades"]] == [str(cena.loja_a)]
    ambas = rede(sa_conn, cena, cena.loja_a, cena.loja_b)
    assert [g["nome"] for g in ambas["grupos"]] == sorted(g["nome"] for g in ambas["grupos"])
    por_loja = {g["id"]: sum(p["faturamento"] for p in g["serie_diaria"]) for g in ambas["grupos"]}
    assert por_loja == {str(cena.loja_a): 200.0, str(cena.loja_b): 300.0}
    assert ambas["atual"]["faturamento"] == 500.0


def test_periodo_anterior_e_filtros_de_canal_e_categoria(sa_conn, cena):
    venda(cena, cena.loja_a, 1, quando=em(10))
    venda(cena, cena.loja_a, 1, canal="online", quando=em(10))
    venda(cena, cena.loja_a, 4, quando=em(10, mes=8))  # periodo anterior
    cena.c.pedido(cena.loja_a, cena.cliente, [(cena.cal, 1, 200)], quando=em(12))
    d = rede(sa_conn, cena)
    assert d["anterior"]["faturamento"] == 400.0 and d["atual"]["faturamento"] == 400.0
    assert linha(d, cena.loja_a)["faturamento_anterior"] == 400.0
    assert rede(sa_conn, cena, canal="online")["atual"]["faturamento"] == 100.0
    calcas = rede(sa_conn, cena, categoria="Calcas")
    assert calcas["atual"]["faturamento"] == 200.0
    assert [(c["categoria"], c["faturamento"]) for c in calcas["grupos"][0]["categorias"]] == [
        ("Calcas", 200.0)
    ]


def test_estoque_conta_peca_esgotada_pelo_saldo_somado(sa_conn, cena):
    c = cena.c
    c.estoque(cena.loja_a, cena.cam_p, 0)
    c.estoque(cena.loja_b, cena.cam_p, 5)  # em outra loja: a peca nao esta esgotada na rede
    c.estoque(cena.loja_a, cena.cam_m, 0)
    c.estoque(cena.loja_b, cena.cam_m, 0)
    c.estoque(cena.loja_a, cena.cal, 7)
    rede_toda = rede(sa_conn, cena)
    assert linha(rede_toda, cena.loja_a)["unidades_em_estoque"] == 7
    assert linha(rede_toda, cena.loja_a)["pecas_esgotadas"] == 2
    assert linha(rede_toda, cena.loja_b)["pecas_esgotadas"] == 1
    assert rede_toda["estoque"]["unidades"] >= 12
    so_a = rede(sa_conn, cena, cena.loja_a)
    assert so_a["estoque"] == {"unidades": 7, "pecas": 3, "pecas_esgotadas": 2}
    assert rede(sa_conn, cena, cena.loja_a, categoria="Calcas")["estoque"] == {
        "unidades": 7,
        "pecas": 1,
        "pecas_esgotadas": 0,
    }


def test_atendimento_por_loja_e_motivos(sa_conn, cena):
    fab = cena.fab
    fab.atendimento(cliente=cena.cliente, loja=cena.loja_a, categoria="entrega", aberto_em=em(10))
    fab.atendimento(cliente=cena.cliente, loja=cena.loja_a, status="resolvido", aberto_em=em(11))
    fab.atendimento(cliente=cena.cliente, loja=cena.loja_b, aberto_em=em(12))
    d = rede(sa_conn, cena)
    assert linha(d, cena.loja_a)["chamados_abertos"] == 1
    assert linha(d, cena.loja_b)["chamados_abertos"] == 1
    assert d["atendimento"]["atual"]["total"] == 3
    assert d["atendimento"]["atual"]["resolvidos"] == 1
    assert next(m for m in d["grupos"][0]["motivos"] if m["codigo"] == "entrega")["total"] == 1
    so_a = rede(sa_conn, cena, cena.loja_a)
    assert so_a["atendimento"]["atual"]["total"] == 2
    assert so_a["atendimento"]["abertos_agora"] == 1
    assert sum(m["total"] for m in so_a["grupos"][0]["motivos"]) == 2


def test_sem_dados_tudo_zera_sem_erro(sa_conn, cena):
    d = rede(sa_conn, cena, cena.loja_b)
    assert d["atual"]["faturamento"] == 0.0 and d["pecas_mais_vendidas"] == []
    assert linha(d, cena.loja_b)["resposta_media_horas"] is None
    assert len(d["grupos"][0]["serie_diaria"]) == 30
