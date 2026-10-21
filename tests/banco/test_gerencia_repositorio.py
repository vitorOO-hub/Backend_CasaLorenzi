"""O inicio do gerente contra um Postgres real: vendas, reposicao e pendencias."""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.erros_auth import SemPermissao
from app.core.papeis import Papel, UsuarioAtual
from app.gerencia import repositorio, service
from app.gerencia.repositorio import Filtro

pytestmark = pytest.mark.banco

BRT = timezone(timedelta(hours=-3))
INICIO, FIM = date(2026, 9, 1), date(2026, 9, 30)


def em(dia: int, hora: int = 12, minuto: int = 0, mes: int = 9) -> datetime:
    return datetime(2026, mes, dia, hora, minuto, tzinfo=BRT)


class Cena:
    """Monta produtos, estoque e pedidos direto no banco (mesma transacao da conexao do teste)."""

    def __init__(self, fab):
        self.fab = fab
        self.c = fab.conn

    def _um(self, comando, parametros=()):
        return self.c.execute(comando, parametros).fetchone()[0]

    def produto(self, nome, categoria="Camisas", ativo=True):
        return self._um(
            "INSERT INTO produto (nome, marca, categoria, preco_base, ativo) "
            "VALUES (%s, 'Casa Lorenzi', %s, 100, %s) RETURNING id_produto",
            (nome, categoria, ativo),
        )

    def variacao(self, id_produto, sku, preco=100, ativa=True):
        return self._um(
            "INSERT INTO variacao_produto (id_produto, sku, cor, tamanho, preco_venda, ativa) "
            "VALUES (%s, %s, 'Branco', %s, %s, %s) RETURNING id_variacao",
            (id_produto, sku, sku, preco, ativa),
        )

    def estoque(self, loja, variacao, quantidade, minimo=0):
        self.c.execute(
            "INSERT INTO estoque (id_loja, id_variacao, quantidade, estoque_minimo) "
            "VALUES (%s, %s, %s, %s)",
            (loja, variacao, quantidade, minimo),
        )

    def pedido(self, loja, cliente, itens, *, status="pago", canal="loja", quando=None, frete=0):
        """`itens` = [(id_variacao, quantidade, preco_unitario)]."""
        subtotal = sum(q * p for _, q, p in itens)
        id_pedido = self._um(
            """
            INSERT INTO pedido (numero_pedido, id_loja, id_cliente, id_status_pedido,
                                valor_total, canal_venda, valor_frete, criado_em)
            VALUES (%s, %s, %s,
                    (SELECT id_status_pedido FROM status_pedido WHERE codigo = %s),
                    %s, %s, %s, %s)
            RETURNING id_pedido
            """,
            (
                f"T-{uuid4().hex[:12]}",
                loja,
                cliente.id,
                status,
                subtotal + frete,
                canal,
                frete,
                quando or em(10),
            ),
        )
        for variacao, quantidade, preco in itens:
            self.c.execute(
                "INSERT INTO item_pedido (id_pedido, id_variacao, quantidade, preco_unitario) "
                "VALUES (%s, %s, %s, %s)",
                (id_pedido, variacao, quantidade, preco),
            )
        return id_pedido

    def ajuste(self, loja, variacao, solicitante, *, status="pendente", decisor=None):
        decidido_em = datetime.now(BRT) if decisor else None
        self.c.execute(
            """
            INSERT INTO ajuste_estoque (id_loja, id_variacao, id_usuario_solicitante,
                                        id_usuario_decisor, quantidade, motivo, status, decidido_em,
                                        motivo_recusa)
            VALUES (%s, %s, %s, %s, -1, 'Quebra', %s, %s, %s)
            """,
            (
                loja,
                variacao,
                solicitante.id,
                decisor.id if decisor else None,
                status,
                decidido_em,
                "Sem justificativa" if status == "rejeitado" else None,
            ),
        )

    def transferencia(self, *, tipo, status, origem, destino, variacao, solicitante):
        self.c.execute(
            """
            INSERT INTO transferencia_estoque (
                id_tipo_transferencia_estoque, id_status_transferencia_estoque,
                id_loja_origem, id_loja_destino, id_variacao, id_usuario_solicitante, quantidade)
            VALUES (
                (SELECT id_tipo_transferencia_estoque FROM tipo_transferencia_estoque
                 WHERE codigo = %s),
                (SELECT id_status_transferencia_estoque FROM status_transferencia_estoque
                 WHERE codigo = %s),
                %s, %s, %s, %s, 2)
            """,
            (tipo, status, origem, destino, variacao, solicitante.id),
        )


@pytest.fixture
def cena(fab_sa):
    fab = fab_sa
    c = Cena(fab)
    loja_a, loja_b = fab.loja(), fab.loja()
    cliente = fab.usuario("cliente")
    camisa, calca = c.produto("Camisa Teste"), c.produto("Calca Teste", "Calcas")
    cam_p, cam_m = (
        c.variacao(camisa, f"CAM-P-{uuid4().hex[:6]}"),
        c.variacao(camisa, f"CAM-M-{uuid4().hex[:6]}"),
    )
    cal = c.variacao(calca, f"CAL-{uuid4().hex[:6]}", 200)
    return SimpleNamespace(
        c=c,
        fab=fab,
        loja_a=loja_a,
        loja_b=loja_b,
        cliente=cliente,
        cam_p=cam_p,
        cam_m=cam_m,
        cal=cal,
        camisa=camisa,
        calca=calca,
        gerente_a=fab.usuario("gerente_loja", loja=loja_a),
    )


def resumo(conn, filtro, inicio=INICIO, fim=FIM):
    return repositorio.resumo(conn, filtro, inicio, fim)


# ------------------------------------------------------------------ vendas


def test_so_pedido_pago_separado_ou_entregue_vira_venda(sa_conn, cena):
    c, a = cena.c, cena.loja_a
    for status in ("pago", "separado", "entregue", "criado", "aguardando_pagamento", "cancelado"):
        c.pedido(a, cena.cliente, [(cena.cam_p, 1, 100)], status=status)
    r = resumo(sa_conn, Filtro(a))
    assert (r["pedidos"], float(r["faturamento"]), r["pecas"]) == (3, 300.0, 3)


def test_faturamento_nao_inclui_frete(sa_conn, cena):
    cena.c.pedido(cena.loja_a, cena.cliente, [(cena.cam_p, 2, 100)], canal="online", frete=49)
    r = resumo(sa_conn, Filtro(cena.loja_a))
    assert float(r["faturamento"]) == 200.0  # o pedido vale 249; o frete nao e receita de produto
    assert r["pecas"] == 2 and r["pedidos"] == 1


def test_vendas_de_outra_loja_nao_entram(sa_conn, cena):
    cena.c.pedido(cena.loja_a, cena.cliente, [(cena.cam_p, 1, 100)])
    cena.c.pedido(cena.loja_b, cena.cliente, [(cena.cam_p, 5, 100)])
    assert resumo(sa_conn, Filtro(cena.loja_a))["pedidos"] == 1
    assert resumo(sa_conn, Filtro(cena.loja_b))["pecas"] == 5
    assert resumo(sa_conn, Filtro(None))["pedidos"] == 2  # a rede inteira


def test_filtro_de_canal(sa_conn, cena):
    c, a = cena.c, cena.loja_a
    c.pedido(a, cena.cliente, [(cena.cam_p, 1, 100)], canal="loja")
    c.pedido(a, cena.cliente, [(cena.cam_p, 3, 100)], canal="online")
    assert resumo(sa_conn, Filtro(a, canal="online"))["pecas"] == 3
    assert resumo(sa_conn, Filtro(a, canal="loja"))["pecas"] == 1
    r = resumo(sa_conn, Filtro(a))
    assert (float(r["faturamento_online"]), r["pedidos_online"]) == (300.0, 1)


def test_filtro_de_categoria_conta_so_os_itens_da_categoria(sa_conn, cena):
    c, a = cena.c, cena.loja_a
    c.pedido(a, cena.cliente, [(cena.cam_p, 1, 100), (cena.cal, 1, 200)])  # misto
    c.pedido(a, cena.cliente, [(cena.cal, 2, 200)])
    r = resumo(sa_conn, Filtro(a, categoria="Camisas"))
    assert (r["pedidos"], float(r["faturamento"]), r["pecas"]) == (1, 100.0, 1)
    r = resumo(sa_conn, Filtro(a, categoria="Calcas"))
    assert (r["pedidos"], float(r["faturamento"]), r["pecas"]) == (2, 600.0, 3)
    assert resumo(sa_conn, Filtro(a, categoria="Inexistente"))["pedidos"] == 0


def test_periodo_usa_o_dia_de_sao_paulo(sa_conn, cena):
    c, a = cena.c, cena.loja_a
    c.pedido(a, cena.cliente, [(cena.cam_p, 1, 100)], quando=em(30, 23, 30))  # ainda dia 30
    c.pedido(a, cena.cliente, [(cena.cam_p, 1, 100)], quando=em(1, 0, 30, mes=10))  # ja e outubro
    c.pedido(a, cena.cliente, [(cena.cam_p, 1, 100)], quando=em(1, 0, 0))  # primeiro instante
    c.pedido(a, cena.cliente, [(cena.cam_p, 1, 100)], quando=em(31, 23, 59, mes=8))  # agosto
    assert resumo(sa_conn, Filtro(a))["pedidos"] == 2


def test_serie_diaria_tem_um_ponto_por_dia_e_fecha_com_o_resumo(sa_conn, cena):
    c, a = cena.c, cena.loja_a
    c.pedido(a, cena.cliente, [(cena.cam_p, 1, 100)], quando=em(2))
    c.pedido(a, cena.cliente, [(cena.cam_m, 2, 100)], quando=em(2, 18))
    c.pedido(a, cena.cliente, [(cena.cal, 1, 200)], quando=em(15))
    serie = repositorio.serie_diaria(sa_conn, Filtro(a), INICIO, FIM)
    assert len(serie) == 30
    assert [s["data"] for s in serie][:2] == [date(2026, 9, 1), date(2026, 9, 2)]
    dia2 = serie[1]
    assert (dia2["pedidos"], float(dia2["faturamento"]), dia2["pecas"]) == (2, 300.0, 3)
    assert sum(float(s["faturamento"]) for s in serie) == float(
        resumo(sa_conn, Filtro(a))["faturamento"]
    )
    assert serie[0]["pedidos"] == 0 and float(serie[0]["faturamento"]) == 0.0


def test_movimento_por_dia_da_semana(sa_conn, cena):
    c, a = cena.c, cena.loja_a
    # 2026-09-06 e 2026-09-13 sao domingos; 2026-09-09 e quarta.
    for dia in (6, 6, 13):
        c.pedido(a, cena.cliente, [(cena.cam_p, 1, 100)], quando=em(dia))
    c.pedido(a, cena.cliente, [(cena.cam_p, 1, 100)], quando=em(9))
    semana = {
        s["dia_semana"]: s for s in repositorio.movimento_semana(sa_conn, Filtro(a), INICIO, FIM)
    }
    assert sorted(semana) == [0, 1, 2, 3, 4, 5, 6]
    assert (semana[0]["pedidos"], semana[0]["dias"]) == (3, 4)  # domingos 6, 13, 20 e 27
    assert (semana[3]["pedidos"], semana[3]["dias"]) == (1, 5)  # quartas 2, 9, 16, 23 e 30
    assert sum(s["dias"] for s in semana.values()) == 30


def test_pecas_mais_vendidas_somam_as_variacoes_do_produto(sa_conn, cena):
    c, a = cena.c, cena.loja_a
    c.pedido(a, cena.cliente, [(cena.cam_p, 2, 100), (cena.cam_m, 3, 100)])
    c.pedido(a, cena.cliente, [(cena.cal, 4, 200)])
    ranking = repositorio.pecas_mais_vendidas(sa_conn, Filtro(a), INICIO, FIM, limite=10)
    assert [(r["nome"], r["unidades"]) for r in ranking] == [
        ("Camisa Teste", 5),
        ("Calca Teste", 4),
    ]
    assert ranking[0]["nome"] == "Camisa Teste" and float(ranking[0]["faturamento"]) == 500.0
    assert len(repositorio.pecas_mais_vendidas(sa_conn, Filtro(a), INICIO, FIM, limite=1)) == 1


def test_sem_vendas_tudo_zera_sem_erro(sa_conn, cena):
    r = resumo(sa_conn, Filtro(cena.loja_a))
    assert (r["pedidos"], float(r["faturamento"]), r["pecas"]) == (0, 0.0, 0)
    assert (
        repositorio.pecas_mais_vendidas(sa_conn, Filtro(cena.loja_a), INICIO, FIM, limite=6) == []
    )


def test_categoria_digitada_com_aspas_nao_quebra_a_consulta(sa_conn, cena):
    assert resumo(sa_conn, Filtro(cena.loja_a, categoria="x' OR '1'='1"))["pedidos"] == 0


# ------------------------------------------------------------------ service


def usuario(cena, papel=Papel.GERENTE_LOJA, loja="a"):
    id_loja = None if papel is Papel.ADMIN else (cena.loja_a if loja == "a" else cena.loja_b)
    return UsuarioAtual(id_auth=cena.gerente_a.auth, papel=papel, id_loja=id_loja)


def test_dashboard_compara_com_o_periodo_anterior(sa_conn, cena):
    c, a = cena.c, cena.loja_a
    c.pedido(a, cena.cliente, [(cena.cam_p, 1, 100)], canal="online", frete=30, quando=em(10))
    c.pedido(a, cena.cliente, [(cena.cam_p, 3, 100)], quando=em(11))
    c.pedido(a, cena.cliente, [(cena.cam_p, 1, 100)], quando=em(10, mes=8))  # periodo anterior
    d = service.montar_dashboard(sa_conn, usuario(cena), inicio=INICIO, fim=FIM, filtro=Filtro(a))
    assert d["periodo_anterior"] == {"inicio": date(2026, 8, 2), "fim": date(2026, 8, 31)}
    assert d["atual"]["faturamento"] == 400.0 and d["atual"]["pedidos"] == 2
    assert d["atual"]["ticket_medio"] == 200.0
    assert d["atual"]["participacao_online"] == 0.25
    assert d["anterior"]["pedidos"] == 1 and d["anterior"]["faturamento"] == 100.0
    assert d["escopo"]["loja_nome"] and d["escopo"]["pode_escolher_loja"] is False
    assert {o["codigo"] for o in d["opcoes"]["canais"]} == {"loja", "online"}
    assert "Camisas" in d["opcoes"]["categorias"]
    # 10/09 e quinta; o mes tem 4 quintas e 1 pedido nelas.
    assert [m["pedidos_por_dia"] for m in d["movimento_semana"] if m["dia_semana"] == 4] == [0.25]


def test_dashboard_do_gerente_lista_so_a_propria_loja_e_o_do_admin_todas(sa_conn, cena):
    gerente = service.montar_dashboard(
        sa_conn, usuario(cena), inicio=INICIO, fim=FIM, filtro=Filtro(cena.loja_a)
    )
    assert [str(x["id_loja"]) for x in gerente["opcoes"]["lojas"]] == [str(cena.loja_a)]
    admin = service.montar_dashboard(
        sa_conn, usuario(cena, Papel.ADMIN), inicio=INICIO, fim=FIM, filtro=Filtro(None)
    )
    ids = {str(x["id_loja"]) for x in admin["opcoes"]["lojas"]}
    assert {str(cena.loja_a), str(cena.loja_b)} <= ids
    assert admin["escopo"]["pode_escolher_loja"] is True and admin["escopo"]["loja_nome"] is None


def test_escopo_de_loja_do_service(cena):
    assert service.loja_do_escopo(usuario(cena), None) == cena.loja_a
    assert service.loja_do_escopo(usuario(cena), cena.loja_a) == cena.loja_a
    with pytest.raises(SemPermissao):
        service.loja_do_escopo(usuario(cena), cena.loja_b)
    assert service.loja_do_escopo(usuario(cena, Papel.ADMIN), None) is None
    assert service.loja_do_escopo(usuario(cena, Papel.ADMIN), cena.loja_b) == cena.loja_b
    with pytest.raises(SemPermissao):
        service.loja_do_escopo(usuario(cena, Papel.ATENDENTE), None)


# ------------------------------------------------------------------ reposicao


def reposicao(conn, filtro, limite=50):
    total, itens = repositorio.reposicao(conn, filtro, limite=limite)
    return total, {i["sku"]: i for i in itens}, [i["sku"] for i in itens]


def test_reposicao_lista_esgotada_abaixo_do_minimo_e_cobertura_curta(sa_conn, cena):
    c, a = cena.c, cena.loja_a
    esgotada = c.variacao(cena.camisa, "REP-ESGOTADA")
    abaixo = c.variacao(cena.camisa, "REP-ABAIXO")
    curta = c.variacao(cena.camisa, "REP-CURTA")
    folgada = c.variacao(cena.camisa, "REP-FOLGADA")
    parada = c.variacao(cena.camisa, "REP-PARADA")
    c.estoque(a, esgotada, 0, 3)
    c.estoque(a, abaixo, 2, 2)
    c.estoque(a, curta, 10, 1)
    c.estoque(a, folgada, 500, 5)
    c.estoque(a, parada, 40, 5)  # sem giro e acima do minimo: sem pressa
    agora = datetime.now(BRT)
    # 30 pecas em 30 dias = 1 por dia: a curta (10) acaba em ~10 dias; a folgada (500) nao.
    c.pedido(a, cena.cliente, [(curta, 30, 100)], quando=agora - timedelta(days=5))
    c.pedido(a, cena.cliente, [(folgada, 30, 100)], quando=agora - timedelta(days=5))
    total, por_sku, ordem = reposicao(sa_conn, Filtro(a))
    assert total == 3 and set(por_sku) == {"REP-ESGOTADA", "REP-ABAIXO", "REP-CURTA"}
    assert ordem[0] == "REP-ESGOTADA"  # esgotada sempre primeiro
    assert por_sku["REP-ESGOTADA"]["situacao"] == "esgotada"
    assert por_sku["REP-ABAIXO"]["situacao"] == "abaixo_do_minimo"
    assert por_sku["REP-CURTA"]["situacao"] == "cobertura_curta"
    assert float(por_sku["REP-CURTA"]["dias_cobertura"]) == pytest.approx(10.0)
    assert float(por_sku["REP-CURTA"]["giro_diario"]) == pytest.approx(1.0)
    assert por_sku["REP-ABAIXO"]["dias_cobertura"] is None  # sem giro, sem previsao


def test_reposicao_ignora_pedido_cancelado_e_venda_antiga(sa_conn, cena):
    c, a = cena.c, cena.loja_a
    v = c.variacao(cena.camisa, "REP-GIRO")
    c.estoque(a, v, 10, 1)
    agora = datetime.now(BRT)
    c.pedido(a, cena.cliente, [(v, 30, 100)], status="cancelado", quando=agora - timedelta(days=3))
    c.pedido(a, cena.cliente, [(v, 30, 100)], quando=agora - timedelta(days=60))  # fora dos 30 dias
    assert reposicao(sa_conn, Filtro(a))[0] == 0


def test_reposicao_soma_a_rede_sem_loja_e_separa_com_loja(sa_conn, cena):
    c = cena.c
    v = c.variacao(cena.camisa, "REP-REDE")
    c.estoque(cena.loja_a, v, 1, 5)
    c.estoque(cena.loja_b, v, 20, 5)
    _, por_sku, _ = reposicao(sa_conn, Filtro(cena.loja_a))
    assert por_sku["REP-REDE"]["saldo"] == 1
    assert "REP-REDE" not in reposicao(sa_conn, Filtro(cena.loja_b))[1]
    assert "REP-REDE" not in reposicao(sa_conn, Filtro(None))[1]  # 21 contra minimo 10


def test_reposicao_filtra_categoria_ignora_inativos_e_limita(sa_conn, cena):
    c, a = cena.c, cena.loja_a
    inativa = c.variacao(cena.camisa, "REP-INATIVA", ativa=False)
    produto_inativo = c.produto("Fora de linha", "Camisas", ativo=False)
    fora = c.variacao(produto_inativo, "REP-FORA")
    calca = c.variacao(cena.calca, "REP-CALCA")
    c.estoque(a, inativa, 0, 3)
    c.estoque(a, fora, 0, 3)
    c.estoque(a, calca, 0, 3)
    for i in range(4):
        c.estoque(a, c.variacao(cena.camisa, f"REP-C{i}"), 0, 2)
    total, por_sku, _ = reposicao(sa_conn, Filtro(a, categoria="Camisas"))
    assert total == 4 and not {"REP-INATIVA", "REP-FORA", "REP-CALCA"} & set(por_sku)
    assert list(reposicao(sa_conn, Filtro(a, categoria="Calcas"))[1]) == ["REP-CALCA"]
    mostrados = repositorio.reposicao(sa_conn, Filtro(a, categoria="Camisas"), limite=2)
    assert mostrados[0] == 4 and len(mostrados[1]) == 2  # total real, lista cortada


# ------------------------------------------------------------------ pendencias


def test_ajustes_para_aprovar_contam_so_os_pendentes_da_loja(sa_conn, cena):
    c, a, b = cena.c, cena.loja_a, cena.loja_b
    operador = cena.fab.usuario("operador_estoque", loja=a)
    c.ajuste(a, cena.cam_p, operador)
    c.ajuste(a, cena.cam_m, operador)
    c.ajuste(a, cena.cal, operador, status="aprovado", decisor=cena.gerente_a)
    c.ajuste(a, cena.cal, operador, status="rejeitado", decisor=cena.gerente_a)
    c.ajuste(b, cena.cam_p, operador)
    assert repositorio.ajustes_para_aprovar(sa_conn, Filtro(a)) == 2
    assert repositorio.ajustes_para_aprovar(sa_conn, Filtro(b)) == 1
    assert repositorio.ajustes_para_aprovar(sa_conn, Filtro(None)) == 3


def test_transferencias_aguardando_a_decisao_da_loja(sa_conn, cena):
    c, a, b = cena.c, cena.loja_a, cena.loja_b
    outra = cena.fab.loja()
    s = cena.gerente_a

    def nova(tipo, status, origem, destino):
        c.transferencia(
            tipo=tipo,
            status=status,
            origem=origem,
            destino=destino,
            variacao=cena.cam_p,
            solicitante=s,
        )

    nova("transferencia", "solicitada", a, b)  # pedem a A: A decide
    nova("transferencia", "solicitada", b, a)  # A pediu a B: espera B, nao A
    nova("transferencia", "aceita", a, b)  # ja decidida
    nova("reposicao_rede", "solicitada", None, b)  # B pediu a rede: A pode atender
    nova("reposicao_rede", "solicitada", None, a)  # a propria reposicao de A nao e dela
    nova("reposicao_rede", "solicitada", None, outra)
    assert repositorio.transferencias_aguardando(sa_conn, Filtro(a)) == 3
    assert repositorio.transferencias_aguardando(sa_conn, Filtro(None)) == 6  # solicitadas e em transito


def test_pendencias_juntam_os_tres_numeros(sa_conn, cena):
    c, a = cena.c, cena.loja_a
    c.ajuste(a, cena.cam_p, cena.fab.usuario("operador_estoque", loja=a))
    cena.fab.atendimento(cliente=cena.cliente, loja=a)  # aberto, sem resposta
    cena.fab.atendimento(cliente=cena.cliente, loja=None)  # sem loja: a equipe tambem atende
    cena.fab.atendimento(cliente=cena.cliente, loja=cena.loja_b)  # de outra loja
    p = service.montar_pendencias(sa_conn, Filtro(a), incluir_chamados_sem_loja=True)
    assert p == {
        "ajustes_para_aprovar": 1,
        "transferencias_aguardando": 0,
        "chamados_sem_resposta": 2,
        "total": 3,
    }
    sem = service.montar_pendencias(sa_conn, Filtro(a), incluir_chamados_sem_loja=False)
    assert sem["chamados_sem_resposta"] == 1
