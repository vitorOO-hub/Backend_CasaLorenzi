"""Saldo de pontos com vencimento.

Regras (decisão do time, conferidas contra a planilha final):
- o saldo da coluna Pontos foi congelado em 01/01/2025: ele entra como um crédito nessa data;
- depois disso valem as movimentações do banco (vulto.db);
- créditos de compra são recalculados pela regra do programa (R$ 1 = 1 ponto, site e app em dobro);
  compras canceladas, aguardando, estornadas ou com chargeback não dão pontos, e o estorno
  delas no banco é ignorado para não descontar duas vezes;
- ajustes "correcao bug app" desfaziam créditos inflados pelos centavos do app; como o crédito
  é recalculado, eles são ignorados (os demais ajustes, como bônus e cortesias, valem);
- resgates consomem primeiro os pontos mais antigos;
- na data de referência, vence o que foi creditado há 365 dias ou mais e não foi usado.
"""
from datetime import datetime, timedelta

from .regras import SP

CONGELAMENTO = datetime(2025, 1, 1, tzinfo=SP)
VALIDADE = timedelta(days=365)


def eventos_do_banco(movimentos):
    """(quando, pontos) de cada movimentação: crédito positivo, resgate negativo."""
    saida = []
    for m in movimentos:
        if m.tipo == 'C' and m.compra is not None:
            if m.compra.da_pontos:
                saida.append((m.quando, m.compra.pontos))
        elif m.tipo == 'E':
            if m.compra is None or m.compra.da_pontos:
                saida.append((m.quando, m.qtd))
        elif m.tipo == 'D':
            saida.append((m.quando, -m.qtd))
        elif m.tipo == 'AJ' and m.obs.startswith('correcao bug app'):
            # Ajuste que corrigia crédito inflado pelos centavos do app: o crédito já é recalculado.
            continue
        else:  # C sem compra ligada e AJ (ajuste manual) entram como estão
            saida.append((m.quando, m.qtd))
    return saida


def saldo(eventos, referencia):
    """Saldo na data de referência: resgates consomem os créditos mais antigos; o que sobra
    de créditos com 365 dias ou mais vence. Nunca negativo."""
    lotes = []
    for quando, pontos in sorted(eventos, key=lambda e: e[0]):
        if pontos > 0:
            lotes.append([quando, pontos])
            continue
        falta = -pontos
        for lote in lotes:
            if falta <= 0:
                break
            usado = min(lote[1], falta)
            lote[1] -= usado
            falta -= usado
    validos = sum(p for quando, p in lotes if quando + VALIDADE > referencia)
    return max(0, validos)


def creditos_no_ano(eventos, referencia):
    """Pontos creditados no ano da data de referência (base da categoria)."""
    return sum(p for quando, p in eventos if p > 0 and quando.year == referencia.year and quando <= referencia)
