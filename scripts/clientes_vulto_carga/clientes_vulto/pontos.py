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
    """(quando, pontos, tipo, descrição) de cada movimentação: crédito positivo, resgate negativo."""
    saida = []
    for m in movimentos:
        if m.tipo == 'C' and m.compra is not None:
            if m.compra.da_pontos:
                saida.append((m.quando, m.compra.pontos, 'credito', f'compra {m.compra.id} do banco antigo'))
        elif m.tipo == 'E':
            if m.compra is None or m.compra.da_pontos:
                saida.append((m.quando, m.qtd, 'estorno', 'estorno do banco antigo'))
        elif m.tipo == 'D':
            saida.append((m.quando, -m.qtd, 'resgate', 'resgate do banco antigo'))
        elif m.tipo == 'AJ' and m.obs.startswith('correcao bug app'):
            # Ajuste que corrigia crédito inflado pelos centavos do app: o crédito já é recalculado.
            continue
        elif m.tipo == 'AJ':
            saida.append((m.quando, m.qtd, 'ajuste', f'ajuste do banco antigo: {m.obs}' if m.obs else 'ajuste do banco antigo'))
        else:  # C sem compra ligada entra como está
            saida.append((m.quando, m.qtd, 'credito', 'crédito do banco antigo'))
    return saida


def saldo(eventos, referencia):
    """Saldo na data de referência: resgates consomem os créditos mais antigos; o que sobra
    de créditos com 365 dias ou mais vence. Nunca negativo."""
    return sum(e['pontos'] for e in extrato(eventos, referencia))


def extrato(eventos, referencia):
    """Os eventos como linhas de extrato, mais o que fecha a conta na data de referência:
    vencimento de cada crédito não usado com 365 dias ou mais, e o perdão de resgate maior que o
    saldo (o banco antigo deixou resgatar sem pontos). A soma das linhas é o saldo."""
    linhas, lotes = [], []
    for quando, pontos, tipo, descricao in sorted(eventos, key=lambda e: e[0]):
        linha = {'tipo': tipo, 'pontos': pontos, 'ocorrido_em': quando, 'vence_em': None, 'descricao': descricao}
        linhas.append(linha)
        if pontos > 0:
            linha['vence_em'] = quando + VALIDADE
            lotes.append([quando, pontos])
            continue
        falta = -pontos
        for lote in lotes:
            if falta <= 0:
                break
            usado = min(lote[1], falta)
            lote[1] -= usado
            falta -= usado
        if falta > 0:
            linhas.append({'tipo': 'ajuste', 'pontos': falta, 'ocorrido_em': quando, 'vence_em': None,
                           'descricao': 'resgate acima do saldo no banco antigo: diferença perdoada na migração'})
    for quando, sobra in lotes:
        if sobra > 0 and quando + VALIDADE <= referencia:
            linhas.append({'tipo': 'vencimento', 'pontos': -sobra, 'ocorrido_em': quando + VALIDADE, 'vence_em': None,
                           'descricao': f'vencimento dos pontos de {quando.astimezone(SP):%d/%m/%Y}'})
    return linhas


def creditos_no_ano(eventos, referencia):
    """Pontos creditados no ano da data de referência (base da categoria)."""
    return sum(e[1] for e in eventos if e[1] > 0 and e[0].year == referencia.year and e[0] <= referencia)
