import sys, openpyxl
from catalogo_vulto.limpeza import limpar
res = limpar(sys.argv[1])
v14 = openpyxl.load_workbook(sys.argv[2])
print('avisos:', len(res.avisos)); [print('  ', a) for a in res.avisos]
tot = dif = 0
campos = ['SKU','PRODUTO','CATEGORIA','COLECAO','COR','TAM','PRECO','CUSTO','EAN','DESCONTINUADA']
alvo = ['SKU','PRODUTO','CATEGORIA','COLEÇÃO','COR','TAM','PRECO','CUSTO','EAN','DESCONTINUADA']
for aba in res.abas:
    ws = v14[aba]; h = [c.value for c in ws[1]]
    esperado = [dict(zip(h, r)) for r in ws.iter_rows(min_row=2, values_only=True) if any(x is not None for x in r)]
    obtido = [r for r in res.linhas if r['ABA'] == aba]
    if len(esperado) != len(obtido): print(aba, 'LINHAS', len(esperado), len(obtido))
    d = 0
    for e, o in zip(esperado, obtido):
        for c, ca in zip(campos, alvo):
            ov = o[c]
            if c in ('PRECO', 'CUSTO') and ov is not None: ov = ov.replace('.', ',')
            tot += 1
            if (ov or None) != (e[ca] or None):
                d += 1; dif += 1
                if d <= 4: print('  DIF', aba, o['LINHA'], c, repr(ov), repr(e[ca]))
    print(aba, 'linhas', len(obtido), 'difs', d)
print('células comparadas', tot, 'diferentes', dif)
