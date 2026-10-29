"""Automacoes do operador de estoque (n8n) contra um Postgres real: reposicao, pendencias paradas e
estoque parado, cada uma na loja certa."""

from types import SimpleNamespace

import pytest

from app.automacoes import service

pytestmark = pytest.mark.banco


@pytest.fixture
def cena(fab_sa):
    fab = fab_sa
    c = fab.conn
    a, b, d = fab.loja(), fab.loja(), fab.loja()
    fechada = fab.loja(ativa=False)
    op_a = fab.usuario("operador_estoque", loja=a)
    camisa, calca, blazer = fab.variacao(), fab.variacao(), fab.variacao()

    def estoque(loja, variacao, quantidade, minimo):
        c.execute(
            "INSERT INTO estoque (id_loja, id_variacao, quantidade, estoque_minimo) "
            "VALUES (%s, %s, %s, %s)",
            (loja, variacao, quantidade, minimo),
        )

    estoque(a, camisa, 1, 3)  # abaixo do minimo
    estoque(b, camisa, 10, 2)  # sobra 8
    estoque(d, camisa, 4, 3)  # sobra 1
    estoque(fechada, camisa, 50, 0)  # loja inativa nao entra como sobra
    estoque(a, calca, 5, 0)  # sem minimo definido: nao alerta, e tudo e sobra
    estoque(b, calca, 2, 2)  # no minimo: alerta
    estoque(a, blazer, 4, 1)  # acima do minimo

    def transferencia(origem, destino, status, solicitada, aceita=None):
        tipo = "transferencia" if origem else "reposicao_rede"
        c.execute(
            """
            INSERT INTO transferencia_estoque (
                id_tipo_transferencia_estoque, id_status_transferencia_estoque,
                id_loja_origem, id_loja_destino, id_variacao, id_usuario_solicitante,
                quantidade, solicitada_em, aceita_em)
            VALUES (
                (SELECT id_tipo_transferencia_estoque FROM tipo_transferencia_estoque
                 WHERE codigo = %s),
                (SELECT id_status_transferencia_estoque FROM status_transferencia_estoque
                 WHERE codigo = %s),
                %s, %s, %s, %s, 1, now() - %s::interval, now() - %s::interval)
            """,
            (tipo, status, origem, destino, camisa, op_a.id, solicitada, aceita),
        )

    transferencia(b, a, "solicitada", "30 hours")  # a pediu a b: b responde, a espera
    transferencia(None, d, "solicitada", "2 days")  # reposicao a rede pedida por d
    transferencia(a, b, "solicitada", "2 hours")  # recente: nao e pendencia parada
    transferencia(a, d, "aceita", "6 days", "5 days")  # em transito ha 5 dias: d confirma
    transferencia(b, d, "aceita", "2 days", "1 day")  # em transito ha 1 dia: ainda normal

    c.execute(
        "INSERT INTO ajuste_estoque (id_loja, id_variacao, id_usuario_solicitante, quantidade, "
        "motivo) VALUES (%s, %s, %s, -1, 'peca avariada')",
        (a, blazer, op_a.id),
    )
    return SimpleNamespace(a=a, b=b, d=d, fechada=fechada)


def _por_loja(resposta):
    return {loja["id_loja"]: loja for loja in resposta["lojas"]}


def test_reposicao_mostra_pecas_no_minimo_e_quem_tem_sobra(sa_conn, cena):
    lojas = _por_loja(service.estoque_do_dia(sa_conn, horas=24, dias=3))

    assert cena.fechada not in lojas
    [camisa] = lojas[cena.a]["abaixo_do_minimo"]
    assert (camisa["saldo"], camisa["minimo"]) == (1, 3)
    assert [s["sobra"] for s in camisa["lojas_com_sobra"]] == [8, 1]
    [calca] = lojas[cena.b]["abaixo_do_minimo"]
    assert (calca["saldo"], calca["minimo"]) == (2, 2)
    assert [s["sobra"] for s in calca["lojas_com_sobra"]] == [5]
    assert lojas[cena.d]["abaixo_do_minimo"] == []


def test_transferencia_parada_vai_para_quem_precisa_agir(sa_conn, cena):
    lojas = _por_loja(service.estoque_do_dia(sa_conn, horas=24, dias=3))

    assert len(lojas[cena.b]["para_responder"]) == 1
    assert len(lojas[cena.a]["pedidos_sem_resposta"]) == 1
    # Reposicao a rede sem resposta: so quem pediu e avisado (nao ha origem escolhida).
    [rede] = lojas[cena.d]["pedidos_sem_resposta"]
    assert rede["origem"] is None and rede["tipo"] == "reposicao_rede"
    [em_transito] = lojas[cena.d]["a_receber"]
    assert em_transito["status"] == "aceita"
    # O pedido de 2 horas e a aceita de 1 dia ainda estao no prazo.
    assert lojas[cena.a]["para_responder"] == []
    assert lojas[cena.b]["a_receber"] == []


def test_prazos_vem_dos_parametros(sa_conn, cena):
    lojas = _por_loja(service.estoque_do_dia(sa_conn, horas=1, dias=1))

    assert len(lojas[cena.a]["para_responder"]) == 1  # o pedido de 2 horas passou de 1 hora
    assert len(lojas[cena.d]["a_receber"]) == 1  # a de 1 dia exato ainda nao passou


def test_ajuste_pendente_e_marca_de_pendencias(sa_conn, cena):
    resposta = service.estoque_do_dia(sa_conn, horas=24, dias=3)
    lojas = _por_loja(resposta)

    [ajuste] = lojas[cena.a]["ajustes_pendentes"]
    assert (ajuste["quantidade"], ajuste["motivo"]) == (-1, "peca avariada")
    assert all(lojas[i]["tem_pendencias"] for i in (cena.a, cena.b, cena.d))
    assert resposta["lojas_com_pendencias"] >= 3
    assert "estoque minimo" in resposta["criterios"]["abaixo_do_minimo"]


def test_estoque_parado_vem_separado_por_loja(sa_conn, cena):
    resposta = service.estoque_parado_por_loja(sa_conn, dias=60, limite=20)
    lojas = _por_loja(resposta)

    # Nada foi vendido: toda peca com saldo esta parada, cada uma na sua loja.
    assert lojas[cena.a]["total_itens"] == 3
    assert lojas[cena.a]["total_unidades"] == 10
    assert {i["loja"] for i in lojas[cena.a]["itens"]} == {lojas[cena.a]["loja"]}
    assert lojas[cena.b]["total_itens"] == 2
    assert cena.fechada not in lojas
    assert "60 dias" in resposta["criterio"]
