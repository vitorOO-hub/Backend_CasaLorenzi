"""Leitura e padronização da planilha de catálogo (todas as abas de coleção)."""
import collections
import datetime
import re
import statistics
from dataclasses import dataclass, field

import openpyxl

from .regras import (
    ABAS_SEM_OBS, CABECALHOS, COD3, COLUNAS_REMOVIDAS, LETRA, ORDEM_ABAS, TAMANHOS_FINAIS, VERMELHOS,
    categoria, colecao_da_aba, cor_catalogo, dinheiro, eh_aba_antiga, limpa, norm_cor_base, norm_size,
    parse_sku, sem_acento, tam_sku,
)


@dataclass
class Resultado:
    linhas: list = field(default_factory=list)      # uma por SKU/linha da planilha, já padronizada
    avisos: list = field(default_factory=list)      # (aba, linha, valor, o que aconteceu)
    abas: list = field(default_factory=list)        # abas de catálogo lidas, na ordem da planilha
    ordem: list = field(default_factory=list)       # abas da mais antiga para a mais nova


def _h(v):
    return sem_acento(v).lower().strip() if v is not None else ''


def achar_cabecalho(ws, max_linhas=8):
    """Procura a linha de cabeçalho (qualquer uma das 8 primeiras) e devolve (linha, {campo: coluna}, colunas)."""
    for r in range(1, min(ws.max_row, max_linhas) + 1):
        hs = {c: _h(ws.cell(r, c).value) for c in range(1, ws.max_column + 1)}
        cols = {}
        for campo, nomes in CABECALHOS.items():
            for c, h in hs.items():
                if h in nomes and campo not in cols:
                    cols[campo] = c
        if {'sku', 'cor', 'tam', 'preco'} <= set(cols):
            ate = max(cols.values())
            c = ate + 1
            while c <= ws.max_column and hs.get(c):      # colunas extras coladas à tabela (fornecedor, obs...)
                c += 1
            return r, cols, list(range(1, c))
    return None


def _ler_aba(ws, tab, seq, avisos):
    ach = achar_cabecalho(ws)
    if ach is None:
        return None
    h, cols, todas = ach
    extra_col = next((c for c in todas if c > max(cols.values())), None)
    extra_nome = _h(ws.cell(h, extra_col).value) if extra_col else None
    manter_extra = extra_nome == 'obs' and tab not in ABAS_SEM_OBS and extra_nome not in COLUNAS_REMOVIDAS
    rows = []
    for r in range(h + 1, ws.max_row + 1):
        raw = {k: ws.cell(r, c).value for k, c in cols.items()}
        if all(ws.cell(r, c).value is None for c in todas):
            continue
        cells = [ws.cell(r, c) for c in todas]
        tach = any(c.font and c.font.strike for c in cells)
        verm = any(c.fill and c.fill.fill_type and c.fill.fgColor.type == 'rgb' and c.fill.fgColor.rgb in VERMELHOS
                   for c in cells)
        amar = any(c.fill and c.fill.fill_type and c.fill.fgColor.type == 'rgb' and c.fill.fgColor.rgb == 'FFFFFF00'
                   for c in cells)
        sku_o, nome, cat = raw.get('sku'), raw.get('produto'), raw.get('categoria')
        cor_o, tam_o, preco_o, custo_o, ean = raw.get('cor'), raw.get('tam'), raw.get('preco'), raw.get('custo'), raw.get('ean')
        ex = ws.cell(r, extra_col).value if (extra_col and manter_extra) else None
        f, c3, num, col, tam = parse_sku(limpa(sku_o))
        if f in ('invalido', 'vazio', 'modelo'):
            avisos.append((tab, r, str(sku_o), 'linha de título/texto ou código sem cor/tamanho: não é produto, ignorada'))
            continue
        col = col or norm_cor_base(cor_o)
        if col is None:
            avisos.append((tab, r, str(sku_o), f"cor não identificada (coluna Cor: '{cor_o}'): linha ignorada"))
            continue
        tams = [tam] if tam else [norm_size(s) for s in str(limpa(tam_o)).split('/') if s.strip()]
        grade = (not tam) and len(tams) > 1
        al = []
        if not tam:
            al.append('tamanho veio da coluna Tam' + (' (grade expandida em %d linhas)' % len(tams) if grade else ''))
        p, pa = dinheiro(preco_o)
        cu, ca = dinheiro(custo_o)
        if pa:
            al.append('preço ' + pa)
        if ca == 'vazio':
            al.append('custo vazio')
        elif ca:
            al.append('custo ' + ca + ' (deixado em branco)')
        if p and cu:
            pv, cv = float(p), float(cu)
            if cv >= 1000:
                al.append(f'custo sem vírgula? ({cu} → provável {cv / 100:.2f}) — valor NÃO alterado')
            elif cv > pv:
                al.append('custo maior que o preço — preço/custo invertidos? valor NÃO alterado')
        if amar:
            al.append('estava em amarelo (revisar preço)')
        cor_final = cor_catalogo(cor_o)
        if cor_final is None:
            avisos.append((tab, r, str(sku_o), f"cor '{cor_o}' sem regra de padronização: linha ignorada"))
            continue
        cat_final, mapeada = categoria(limpa(cat), limpa(nome))
        if not mapeada:
            avisos.append((tab, r, str(cat), f"categoria sem regra de padronização (mantida como '{cat_final}')"))
        for t in tams:
            ts = tam_sku(t)
            if ts not in TAMANHOS_FINAIS:
                avisos.append((tab, r, str(tam_o), f"tamanho '{t}' não reconhecido: linha ignorada"))
                continue
            full = f'VLT-{c3}-{num}-{COD3[col]}-{ts}'
            red = f'{c3}{num}{LETRA[col]}{ts}'
            ean_t = re.sub(r'\.0$', '', str(limpa(ean))) if ean is not None else None
            rec = dict(
                SKU=red if f == 'curto_CD' else full, SKU_COMPLETO=full,
                PRODUTO=(limpa(nome) or '').lower() or None, CATEGORIA=cat_final, COR=cor_final, TAM=ts,
                PRECO=p, CUSTO=cu, EAN=ean_t,
                EXTRA=(None if isinstance(ex, datetime.datetime) else limpa(ex)),
                DESCONTINUADA='X' if (tach or verm) else None, ALERTA='; '.join(al) or None,
                ABA=tab, COLECAO=colecao_da_aba(tab), LINHA=r,
                _t=t, _mod=f'{c3}-{num}', _cor=col, _ts=ts, _full=full, _seq=seq[0])
            seq[0] += 1
            rows.append(rec)
    cnt = collections.Counter(x['_full'] for x in rows)
    tamanhos = collections.defaultdict(set)
    for x in rows:
        tamanhos[x['_full']].add(x['_t'])
    for x in rows:
        if cnt[x['_full']] > 1:
            if len(tamanhos[x['_full']]) > 1:
                m = 'SKU igual ao de outra linha: tamanhos ' + ' e '.join(sorted(tamanhos[x['_full']])) + \
                    f" viram o mesmo {x['TAM']} (esta linha: {x['_t']})"
            else:
                m = 'SKU repetido nesta aba (já estava duplicado na origem)'
            x['ALERTA'] = ((x['ALERTA'] + '; ') if x['ALERTA'] else '') + m
    return rows, manter_extra, extra_nome


def _num(x):
    return float(x) if x is not None else None


def _alerta(r, texto):
    r['ALERTA'] = ((r['ALERTA'] + '; ') if r['ALERTA'] else '') + texto


def regra_preco(out):
    """"Se a peça está em duas coleções, vale o MENOR preço." Aba antiga e linhas descontinuadas ficam fora."""
    ativas = [r for t, rs in out.items() if not eh_aba_antiga(t) for r in rs]
    med = {}
    for k in {(r['ABA'], r['_mod']) for r in ativas}:
        v = [_num(r['PRECO']) for r in ativas if (r['ABA'], r['_mod']) == k and r['PRECO']]
        med[k] = statistics.median(v) if v else None

    def preco_ok(r):
        p, c = _num(r['PRECO']), _num(r['CUSTO'])
        if p is None:
            return False
        if c is not None and c < 1000 and p <= c * 1.05:
            return False       # preço igual/menor que o custo (custo >= 1000 é erro de vírgula, não troca)
        m = med[(r['ABA'], r['_mod'])]
        if m and p < 0.6 * m:
            return False       # muito abaixo do resto do modelo
        return True

    menor = {}
    for r in ativas:
        if preco_ok(r) and not r['DESCONTINUADA']:
            menor[r['_mod']] = min(menor.get(r['_mod'], 1e9), _num(r['PRECO']))
    origem = {m: sorted({q['ABA'] for q in ativas if q['_mod'] == m and preco_ok(q) and not q['DESCONTINUADA']
                         and _num(q['PRECO']) == v}) for m, v in menor.items()}
    for r in ativas:
        if r['DESCONTINUADA']:
            if not preco_ok(r):
                old = r['PRECO']
                r['PRECO'], r['CUSTO'] = r['CUSTO'], old
                _alerta(r, f'preço: preço e custo estavam trocados ({old} era o custo); descontinuada, fora da regra do menor preço')
            continue
        mn = menor.get(r['_mod'])
        if mn is None:
            continue
        novo = f'{mn:.2f}'
        old = r['PRECO']
        if old == novo:
            continue
        troca = (not preco_ok(r)) and r['CUSTO'] is not None and _num(old) <= _num(r['CUSTO']) * 1.05
        if troca:
            r['CUSTO'] = old
        n = (('preço e custo estavam trocados (' + str(old) + ' era o custo); ') if troca
             else ('preço parecia erro (' + str(old) + '); ') if not preco_ok(r) else '') + \
            'menor preço do modelo (' + ', '.join(origem[r['_mod']]) + ')'
        r['PRECO'] = novo
        _alerta(r, 'preço: ' + n)


def regra_custo(out, ordem):
    """"Para precificar coleção nova usar o último custo."
    Entre abas: só pelo mesmo SKU, da aba mais nova para a mais antiga. Dentro da aba: custo em branco usa o
    custo do mesmo produto na própria aba. Linhas descontinuadas e a aba antiga não são alteradas."""
    TO = {'PP': 0, 'P': 1, 'M': 2, 'G': 3, 'GG': 4, 'U': 5}

    def valido(r):
        if r['CUSTO'] is None:
            return False
        c = float(r['CUSTO'])
        if c >= 1000:
            return False
        if r['PRECO'] and c > float(r['PRECO']):
            return False
        return True

    allr = [r for t, rs in out.items() for r in rs]
    pool = [r for r in allr if valido(r) and not r['DESCONTINUADA']]
    antiga = lambda r: eh_aba_antiga(r['ABA'])

    def acha(r):
        for crit, nome in ((lambda q: q['_mod'] == r['_mod'] and q['_cor'] == r['_cor'] and q['_t'] == r['_t'], 'mesmo SKU'),
                           (lambda q: q['_mod'] == r['_mod'] and q['_cor'] == r['_cor'] and q['_ts'] == r['_ts'],
                            'mesmo SKU (tamanho equivalente)')):
            for tb in reversed(ordem):
                c = [q for q in pool if q['ABA'] == tb and crit(q)]
                if c:
                    c.sort(key=lambda q: -q['_seq'])
                    return c[0], nome
        return None, None

    alvo = [r for r in allr if not antiga(r)]
    for r in allr:
        r['_old'] = r['CUSTO']
        r['_nota'] = None
    for r in alvo:
        if r['DESCONTINUADA']:
            r['_cnew'] = r['CUSTO'] if valido(r) else None
            continue
        q, nome = acha(r)
        if q is not None:
            r['_cnew'] = q['CUSTO']
            r['_nota'] = f"{nome}, aba {q['ABA']}"
        else:
            r['_cnew'] = None

    def vizinho(r):
        c = [q for q in alvo if q['ABA'] == r['ABA'] and q['_mod'] == r['_mod'] and q['_cnew'] is not None and q is not r
             and (not q['PRECO'] or not r['PRECO'] or float(q['_cnew']) < float(r['PRECO']))]
        if not c:
            return None
        c.sort(key=lambda q: (q['_cor'] != r['_cor'], abs(TO.get(q['_ts'], 9) - TO.get(r['_ts'], 9)), -q['_seq']))
        return c[0]

    for r in alvo:
        if r['_cnew'] is None:
            v = vizinho(r)
            if v is not None:
                r['_cnew'] = v['_cnew']
                r['_nota'] = 'mesmo produto na própria aba (' + ('mesma cor' if v['_cor'] == r['_cor'] else 'outra cor') + ', tamanho ' + v['_ts'] + ')'
    for r in allr:
        if antiga(r):
            r['_cnew'] = r['CUSTO']
            note = 'custo suspeito mantido (aba antiga)' if (not valido(r) and r['CUSTO'] is not None) else None
        else:
            old = r['_old']
            if r['_cnew'] is None:
                note = 'sem custo em nenhuma aba'
            else:
                note = r['_nota']
                if old == r['_cnew']:
                    note = None
        keep = [a for a in (r['ALERTA'] or '').split('; ') if a and not a.startswith('custo')]
        if note:
            keep.append(('custo pelo último custo: ' + note) if not antiga(r) else note)
        r['CUSTO'] = r['_cnew']
        r['ALERTA'] = '; '.join(keep) or None


def limpar(caminho):
    """Lê a planilha original e devolve as linhas padronizadas (ver Resultado)."""
    wb = openpyxl.load_workbook(caminho)
    res = Resultado()
    out = {}
    seq = [0]
    for ws in wb.worksheets:
        lido = _ler_aba(ws, ws.title, seq, res.avisos)
        if lido is None:
            res.avisos.append((ws.title, '—', '', 'aba sem cabeçalho de catálogo (SKU, Cor, Tam, Preço): ignorada'))
            continue
        rows, _, _ = lido
        out[ws.title] = rows
        res.abas.append(ws.title)
    conhecidas = [a for a in ORDEM_ABAS if a in out]
    novas = [a for a in res.abas if a not in ORDEM_ABAS]
    for a in novas:
        res.avisos.append((a, '—', '', 'aba nova, fora da ordem conhecida das coleções: tratada como a coleção mais nova'))
    res.ordem = conhecidas + novas
    regra_preco(out)
    regra_custo(out, res.ordem)
    res.linhas = [r for t in res.abas for r in out[t]]
    return res
