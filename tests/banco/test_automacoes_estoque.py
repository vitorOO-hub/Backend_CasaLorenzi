"""Automacoes do operador de estoque (n8n) contra um Postgres real: reposicao, pendencias paradas e
estoque parado, cada uma na loja certa."""

from datetime import date
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
    cd = fab.loja()  # sem horario de atendimento: CD / e-commerce
    for fisica in (a, b, d):
        c.execute(
            'UPDATE loja SET horario_funcionamento = \'{"seg": "10:00-22:00"}\' WHERE id_loja = %s',
            (fisica,),
        )
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
    estoque(cd, blazer, 40, 0)  # parado no CD: normal, nao vai para o semanal

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
    return SimpleNamespace(a=a, b=b, d=d, fechada=fechada, cd=cd)


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
    assert cena.cd not in lojas
    assert "60 dias" in resposta["criterio"] and "lojas fisicas" in resposta["criterio"]


def test_estoque_do_dia_continua_com_todas_as_lojas_ativas(sa_conn, cena):
    lojas = _por_loja(service.estoque_do_dia(sa_conn, horas=24, dias=3))

    assert cena.cd in lojas


# ---------------------------------------------------------------- relatorios (um fluxo so)

SEGUNDA, SEXTA = date(2026, 11, 2), date(2026, 10, 30)
SITE = "https://exemplo.test"


def _relatorios(sa_conn, semanal, hoje, limite=30):
    return service.relatorios_estoque(
        sa_conn,
        semanal=semanal,
        site=SITE,
        horas=24,
        dias=3,
        dias_parado=60,
        limite=limite,
        hoje=hoje,
    )


def _das_lojas(resposta, cena, tipo):
    minhas = {cena.a, cena.b, cena.d, cena.cd}
    return {
        e["id_loja"]: e for e in resposta["emails"] if e["tipo"] == tipo and e["id_loja"] in minhas
    }


def test_semanal_sai_so_na_segunda(sa_conn, cena):
    sexta = _relatorios(sa_conn, "auto", SEXTA)
    segunda = _relatorios(sa_conn, "auto", SEGUNDA)

    assert sexta["semanal"] is False and _das_lojas(sexta, cena, "semanal") == {}
    assert set(_das_lojas(sexta, cena, "diario")) == {cena.a, cena.b, cena.d}
    assert segunda["semanal"] is True
    # Estoque parado so das lojas fisicas; o CD fica de fora.
    assert set(_das_lojas(segunda, cena, "semanal")) == {cena.a, cena.b, cena.d}


def test_semanal_pode_ser_forcado_ou_cortado(sa_conn, cena):
    forcado = _relatorios(sa_conn, "sim", SEXTA)
    cortado = _relatorios(sa_conn, "nao", SEGUNDA)

    assert forcado["semanal"] is True and _das_lojas(forcado, cena, "semanal")
    assert "fora da segunda" in forcado["motivo_semanal"]
    assert cortado["semanal"] is False and _das_lojas(cortado, cena, "semanal") == {}


def test_email_vai_para_os_operadores_da_loja(sa_conn, cena, fab_sa):
    fab_sa.usuario("operador_estoque", loja=cena.b)
    fab_sa.usuario("operador_estoque", loja=cena.b, ativo=False)
    fab_sa.usuario("vendedor", loja=cena.b)

    diarios = _das_lojas(_relatorios(sa_conn, "auto", SEXTA), cena, "diario")

    assert len(diarios[cena.a]["destinatarios"]) == 1  # o op_a da cena
    assert len(diarios[cena.b]["destinatarios"]) == 1  # so o operador ativo
    assert diarios[cena.d]["destinatarios"] == []


def test_email_do_dia_tem_assunto_html_e_limite(sa_conn, cena):
    diarios = _das_lojas(_relatorios(sa_conn, "auto", SEXTA, limite=1), cena, "diario")

    email = diarios[cena.a]
    assert email["assunto"].endswith("3 itens para resolver")  # minimo, pedido e ajuste
    assert "Abaixo do mínimo · 1" in email["html"]
    assert SITE + "/painel/estoque" in email["html"] and "30/10/2026" in email["html"]
    assert SITE + "/img/logo-casa-lorenzi.png" in email["html"]
    semanal = _das_lojas(_relatorios(sa_conn, "sim", SEXTA, limite=1), cena, "semanal")
    assert "E mais 2 no" in semanal[cena.a]["html"]
