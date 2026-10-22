"""Regra do vencimento de pontos, sem banco: o que vence, quanto e quando avisar."""

from collections import namedtuple
from datetime import timedelta

from app.cliente.vencimento_pontos import CORTE_DA_CARGA, aviso, calcular

M = namedtuple("M", "tipo pontos ocorrido_em vence_em")
ANO = timedelta(days=365)
DIA = timedelta(days=1)


def credito(quando, pontos):
    return M("credito", pontos, quando, quando + ANO)


def saida(quando, pontos, tipo="resgate"):
    return M(tipo, -pontos, quando, None)


def test_lote_que_vence_depois_da_carga_e_lancado_uma_vez():
    entrada = CORTE_DA_CARGA - ANO + 10 * DIA
    movimentos = [credito(entrada, 300)]
    faltam, _ = calcular(movimentos, CORTE_DA_CARGA + 20 * DIA)
    assert [(v["pontos"], v["ocorrido_em"]) for v in faltam] == [(-300, entrada + ANO)]
    # Ja lancado: rodar de novo nao duplica.
    lancado = M("vencimento", -300, entrada + ANO, None)
    assert calcular([*movimentos, lancado], CORTE_DA_CARGA + 20 * DIA)[0] == []


def test_o_que_a_carga_ja_venceu_nao_volta():
    antigo = CORTE_DA_CARGA - ANO - 10 * DIA
    movimentos = [credito(antigo, 500), M("vencimento", -500, antigo + ANO, None)]
    assert calcular(movimentos, CORTE_DA_CARGA + 30 * DIA)[0] == []


def test_saldo_do_corte_fica_nos_lotes_mais_novos():
    velho = CORTE_DA_CARGA - ANO + 5 * DIA
    novo = CORTE_DA_CARGA - 100 * DIA
    # 400 resgatados antes do corte saem do lote velho: dele vencem so 100.
    movimentos = [credito(velho, 500), credito(novo, 200), saida(CORTE_DA_CARGA - 50 * DIA, 400)]
    faltam, _ = calcular(movimentos, CORTE_DA_CARGA + 10 * DIA)
    assert [v["pontos"] for v in faltam] == [-100]


def test_resgate_depois_da_carga_consome_o_mais_antigo_ainda_valido():
    velho = CORTE_DA_CARGA - ANO + 5 * DIA
    novo = CORTE_DA_CARGA - 100 * DIA
    movimentos = [credito(velho, 300), credito(novo, 300), saida(CORTE_DA_CARGA + DIA, 250)]
    faltam, _ = calcular(movimentos, CORTE_DA_CARGA + 10 * DIA)
    assert [v["pontos"] for v in faltam] == [-50]


def test_resgate_depois_do_vencimento_nao_usa_lote_vencido():
    velho = CORTE_DA_CARGA - ANO + 2 * DIA
    novo = CORTE_DA_CARGA - 10 * DIA
    movimentos = [credito(velho, 100), credito(novo, 100), saida(CORTE_DA_CARGA + 5 * DIA, 60)]
    faltam, lotes = calcular(movimentos, CORTE_DA_CARGA + 6 * DIA)
    assert [v["pontos"] for v in faltam] == [-100]  # o velho venceu inteiro antes do resgate
    assert sum(lote.resta for lote in lotes) == 40


def test_credito_sem_validade_nao_vence():
    movimentos = [M("ajuste", 80, CORTE_DA_CARGA - ANO, None)]
    faltam, lotes = calcular(movimentos, CORTE_DA_CARGA + 400 * DIA)
    assert faltam == [] and lotes[0].resta == 80


def test_credito_novo_tambem_vence_um_ano_depois():
    entrada = CORTE_DA_CARGA + DIA
    faltam, _ = calcular([credito(entrada, 70)], entrada + ANO + DIA)
    assert [(v["pontos"], v["ocorrido_em"]) for v in faltam] == [(-70, entrada + ANO)]


def test_aviso_soma_o_que_vence_nos_proximos_30_dias():
    agora = CORTE_DA_CARGA + DIA
    em_10 = agora - ANO + 10 * DIA
    em_40 = agora - ANO + 40 * DIA
    _, lotes = calcular([credito(em_10, 120), credito(em_40, 90)], agora)
    r = aviso(lotes, agora)
    assert r["pontos_a_vencer"] == 120
    assert r["proximos_vencimentos"] == [{"vence_em": em_10 + ANO, "pontos": 120}]
