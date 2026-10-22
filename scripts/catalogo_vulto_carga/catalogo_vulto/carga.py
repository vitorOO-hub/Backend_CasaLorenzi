"""Monta as linhas de public.produto e public.variacao_produto a partir da planilha já padronizada."""
import csv
import json
import os
import uuid
from collections import defaultdict
from decimal import Decimal

from .regras import eh_aba_antiga

def ean13_valido(e):
    """13 dígitos e dígito verificador correto (pesos 1 e 3)."""
    if not (isinstance(e, str) and len(e) == 13 and e.isdigit()):
        return False
    soma = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(e[:12]))
    return (10 - soma % 10) % 10 == int(e[12])


_NS = uuid.UUID('6f1b1e0e-2c1a-4d1e-9f6a-5b7a0c3d9e11')   # fixo: o mesmo modelo gera sempre o mesmo id_produto


def montar(res, incluir_antiga=False, marca=None):
    """Devolve (produtos, variacoes, extras, relatorio, erros).

    - variacao_produto: uma linha por SKU (formato completo VLT-CAT-NNN-COR-TAM).
    - produto: uma linha por modelo (CAT-NNN).
    """
    rank = {aba: i for i, aba in enumerate(res.ordem)}
    rel = []
    grupos = defaultdict(list)
    for r in res.linhas:
        if eh_aba_antiga(r['ABA']) and not incluir_antiga:
            continue
        if r['PRECO'] is None:
            rel.append(('sem preço', r['_full'], f"{r['ABA']} linha {r['LINHA']}: preco_venda é obrigatório, linha não carregada"))
            continue
        grupos[r['_full']].append(r)

    variacoes, extras = [], []
    _rows_modelo = defaultdict(list)
    for sku, g in grupos.items():
        ativos = [r for r in g if not r['DESCONTINUADA']]
        escolhida = max(ativos or g, key=lambda r: (rank[r['ABA']], r['_seq']))
        x = [r for r in g if r['DESCONTINUADA'] and ativos]
        if x:
            rel.append(('SKU reaproveitado', sku, f"{len(x)} linha(s) descontinuada(s) (X) ({', '.join(sorted({r['ABA'] for r in x}))}) "
                        f"descartada(s): o SKU está ativo em {escolhida['ABA']}"))
        mesmos = [r for r in (ativos or g) if r['ABA'] == escolhida['ABA']]
        tams = sorted({r['_t'] for r in mesmos})
        if len(tams) > 1:
            rel.append(('tamanhos no mesmo SKU', sku, f"tamanhos {' e '.join(tams)} viram {escolhida['TAM']}: uma só variação carregada"))
        cores = sorted({r['COR'] for r in g})
        if len(cores) > 1:
            rel.append(('cor diferente entre coleções', sku, f"{' / '.join(cores)}: usada '{escolhida['COR']}' ({escolhida['ABA']})"))
        eans = []
        for r in sorted(g, key=lambda r: (rank[r['ABA']], r['_seq']), reverse=True):
            if r['EAN'] and r['EAN'] not in eans:
                eans.append(r['EAN'])
        ean = escolhida['EAN']
        if not ean:
            rel.append(('sem EAN', sku, f"{escolhida['ABA']} linha {escolhida['LINHA']}: EAN em branco (ean fica vazio)"))
        elif not ean13_valido(ean):
            cortado = ean.isdigit() and ean.endswith('00000')
            rel.append(('EAN inválido', sku, f"{ean}: " + ("termina em zeros, parece EAN cortado pelo Excel (número grande vira notação científica); " if cortado else "")
                        + "não tem 13 dígitos ou o dígito verificador não confere (carregado como está)"))
        if len(eans) > 1:
            rel.append(('EAN diferente entre coleções', sku, f"{' / '.join(eans)}: usado o da coleção {escolhida['COLECAO']}" if ean else ' / '.join(eans)))
        if escolhida['CUSTO'] is None:
            rel.append(('sem custo', sku, f"{escolhida['ABA']} linha {escolhida['LINHA']}: custo em branco (custo fica vazio)"))
        variacoes.append(dict(sku=sku, cor=escolhida['COR'], tamanho=escolhida['TAM'], preco_venda=Decimal(escolhida['PRECO']),
                               custo=Decimal(escolhida['CUSTO']) if escolhida['CUSTO'] is not None else None, ean=ean,
                               ativa=not escolhida['DESCONTINUADA'], modelo=escolhida['_mod'], _linha=escolhida))
        if escolhida['EXTRA']:
            extras.append(dict(sku=sku, obs=escolhida['EXTRA']))
        _rows_modelo[escolhida['_mod']].extend(g)

    por_ean = defaultdict(list)
    for v in variacoes:
        if v['ean']:
            por_ean[v['ean']].append(v['sku'])
    for e, skus in por_ean.items():
        if len(skus) > 1:
            rel.append(('EAN repetido em mais de um SKU', e, ', '.join(skus) + ' (ean gravado vazio: o banco exige EAN único)'))
            for v in variacoes:
                if v['ean'] == e:
                    v['ean'] = None

    por_modelo = defaultdict(list)
    for v in variacoes:
        por_modelo[v['modelo']].append(v)
    produtos = []
    for modelo, vs in sorted(por_modelo.items()):
        ativas = [v for v in vs if v['ativa']]
        base = ativas or vs
        ref = max(base, key=lambda v: (rank[v['_linha']['ABA']], v['_linha']['_seq']))['_linha']
        nomes = {v['_linha']['PRODUTO'] for v in base}
        cats = {v['_linha']['CATEGORIA'] for v in base}
        if len(nomes) > 1:
            rel.append(('modelo com mais de um nome', modelo, ' / '.join(sorted(n or '' for n in nomes)) + f" -> usado: {ref['PRODUTO']}"))
        if len(cats) > 1:
            rel.append(('modelo com mais de uma categoria', modelo, ' / '.join(sorted(cats)) + f" -> usada: {ref['CATEGORIA']}"))
        pid = str(uuid.uuid5(_NS, 'produto:' + modelo))
        linhas_m = _rows_modelo[modelo]
        vivas = [r for r in linhas_m if not r['DESCONTINUADA']] or linhas_m
        colecoes = sorted({r['COLECAO'] for r in vivas}, key=lambda c: min(rank[r['ABA']] for r in vivas if r['COLECAO'] == c))
        produtos.append(dict(id_produto=pid, modelo=modelo, nome=ref['PRODUTO'], marca=marca, categoria=ref['CATEGORIA'],
                             colecao=', '.join(colecoes),
                             preco_base=min(v['preco_venda'] for v in base), ativo=bool(ativas),
                             cores=sorted({v['cor'] for v in base})))
        for v in vs:
            v['id_produto'] = pid
    return produtos, variacoes, extras, rel, validar(produtos, variacoes)


def validar(produtos, variacoes):
    """Repete em Python as restrições (CHECK e UNIQUE) das duas tabelas, para falhar antes de chegar no banco."""
    e = []
    nome_marca, sku_visto, grade, ean_visto = {}, {}, {}, {}
    for p in produtos:
        if not (p['nome'] or '').strip():
            e.append(f"produto {p['modelo']}: nome vazio")
        if p['preco_base'] < 0:
            e.append(f"produto {p['modelo']}: preco_base negativo")
        if not (p['colecao'] or '').strip():
            e.append(f"produto {p['modelo']}: colecao vazia")
        k = (p['nome'], p['marca'])
        if p['marca'] is not None and k in nome_marca:
            e.append(f"produto {p['modelo']}: (nome, marca) repetido com {nome_marca[k]}")
        nome_marca[k] = p['modelo']
    for v in variacoes:
        for campo in ('sku', 'cor', 'tamanho'):
            if not (v[campo] or '').strip():
                e.append(f"variação {v['sku']}: {campo} vazio")
        if v['preco_venda'] < 0:
            e.append(f"variação {v['sku']}: preco_venda negativo")
        if v['custo'] is not None and v['custo'] < 0:
            e.append(f"variação {v['sku']}: custo negativo")
        if v['ean'] is not None and not v['ean'].strip():
            e.append(f"variação {v['sku']}: ean só com espaços (deve ser vazio)")
        if v['ean'] is not None:
            if v['ean'] in ean_visto:
                e.append(f"variação {v['sku']}: EAN {v['ean']} repetido com {ean_visto[v['ean']]}")
            ean_visto[v['ean']] = v['sku']
        if v['sku'] in sku_visto:
            e.append(f"variação {v['sku']}: SKU repetido")
        sku_visto[v['sku']] = 1
        g = (v['id_produto'], v['cor'], v['tamanho'])
        if g in grade:
            e.append(f"variação {v['sku']}: mesma grade (produto, cor, tamanho) de {grade[g]}")
        grade[g] = v['sku']
    return e


def _b(x):
    return 'true' if x else 'false'


def gravar_csv(pasta, produtos, variacoes, extras, rel):
    os.makedirs(pasta, exist_ok=True)

    def w(nome, cab, linhas):
        with open(os.path.join(pasta, nome), 'w', newline='', encoding='utf-8') as f:
            wr = csv.writer(f)
            wr.writerow(cab)
            wr.writerows(linhas)

    w('produto.csv', ['id_produto', 'nome', 'marca', 'categoria', 'colecao', 'preco_base', 'ativo', 'cores'],
      [[p['id_produto'], p['nome'], p['marca'] or '', p['categoria'], p['colecao'], f"{p['preco_base']:.2f}", _b(p['ativo']),
        json.dumps(p['cores'], ensure_ascii=False)] for p in produtos])
    w('variacao_produto.csv', ['sku', 'cor', 'tamanho', 'preco_venda', 'custo', 'ean', 'ativa', 'id_produto'],
      [[v['sku'], v['cor'], v['tamanho'], f"{v['preco_venda']:.2f}", f"{v['custo']:.2f}" if v['custo'] is not None else '',
        v['ean'] or '', _b(v['ativa']), v['id_produto']] for v in variacoes])
    w('campos_sem_tabela.csv', ['sku', 'obs'], [[x['sku'], x['obs']] for x in extras])
    w('relatorio_carga.csv', ['tipo', 'chave', 'detalhe'], rel)


def aplicar(produtos, variacoes, database_url):
    """Grava no Postgres numa única transação (tudo ou nada). Pode ser repetido: atualiza o que já existe."""
    import psycopg
    from psycopg.types.json import Jsonb
    n = dict(produto_novo=0, produto_atualizado=0, variacao=0)
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            ids = {}
            for p in produtos:
                skus = [v['sku'] for v in variacoes if v['modelo'] == p['modelo']]
                cur.execute('select id_produto from public.variacao_produto where sku = any(%s) limit 1', (skus,))
                row = cur.fetchone()
                if row is None and p['marca'] is not None:
                    cur.execute('select id_produto from public.produto where nome = %s and marca = %s', (p['nome'], p['marca']))
                    row = cur.fetchone()
                if row:
                    ids[p['modelo']] = row[0]
                    cur.execute(
                        "update public.produto set categoria = %s, colecao = %s, preco_base = %s, ativo = %s, atualizado_em = now(), "
                        "cores = case when cores = '[]'::jsonb then %s else cores end, "
                        "id_unidade = coalesce(id_unidade, (select id_unidade from public.unidade where nome = lower(%s))) "
                        "where id_produto = %s",
                        (p['categoria'], p['colecao'], p['preco_base'], p['ativo'], Jsonb(p['cores']), p['marca'], row[0]))
                    n['produto_atualizado'] += 1
                else:
                    cur.execute(
                        'insert into public.produto (id_produto, nome, marca, categoria, colecao, preco_base, ativo, cores, id_unidade) '
                        'values (%s, %s, %s, %s, %s, %s, %s, %s, (select id_unidade from public.unidade where nome = lower(%s)))',
                        (p['id_produto'], p['nome'], p['marca'], p['categoria'], p['colecao'], p['preco_base'], p['ativo'], Jsonb(p['cores']), p['marca']))
                    ids[p['modelo']] = p['id_produto']
                    n['produto_novo'] += 1
            for v in variacoes:
                cur.execute(
                    'insert into public.variacao_produto (sku, cor, tamanho, preco_venda, custo, ean, ativa, id_produto) '
                    'values (%s, %s, %s, %s, %s, %s, %s, %s) '
                    'on conflict (sku) do update set cor = excluded.cor, tamanho = excluded.tamanho, '
                    'preco_venda = excluded.preco_venda, custo = excluded.custo, ean = excluded.ean, '
                    'ativa = excluded.ativa, atualizada_em = now()',
                    (v['sku'], v['cor'], v['tamanho'], v['preco_venda'], v['custo'], v['ean'], v['ativa'], ids[v['modelo']]))
                n['variacao'] += 1
    return n
