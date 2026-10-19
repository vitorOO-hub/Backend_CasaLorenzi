"""Uso:
  python -m catalogo_vulto limpar   planilha.xlsx --saida catalogo_padronizado.xlsx
  python -m catalogo_vulto carregar planilha.xlsx --saida-dir saida/                 (só gera CSVs e relatório)
  python -m catalogo_vulto carregar planilha.xlsx --saida-dir saida/ --aplicar       (grava no banco; usa DATABASE_URL)
"""
import argparse
import os
import sys

from . import carga, exporta, limpeza


def main(argv=None):
    ap = argparse.ArgumentParser(prog='catalogo_vulto')
    sub = ap.add_subparsers(dest='cmd', required=True)
    a = sub.add_parser('limpar', help='padroniza a planilha e grava um .xlsx para conferência')
    a.add_argument('planilha')
    a.add_argument('--saida', default='catalogo_padronizado.xlsx')
    b = sub.add_parser('carregar', help='gera as linhas de produto e variacao_produto (e, com --aplicar, grava no banco)')
    b.add_argument('planilha')
    b.add_argument('--saida-dir', default='saida_carga')
    b.add_argument('--incluir-antiga', action='store_true', help='inclui a aba PLANILHA ANTIGA NAO USAR (padrão: fora)')
    b.add_argument('--marca', default='Vulto', help='valor para produto.marca (a planilha não tem marca; padrão: Vulto)')
    b.add_argument('--aplicar', action='store_true', help='grava no Postgres (DATABASE_URL). Sem isso, só gera arquivos.')
    args = ap.parse_args(argv)

    res = limpeza.limpar(args.planilha)
    if args.cmd == 'limpar':
        exporta.gravar_xlsx(args.saida, res)
        print(f'{len(res.linhas)} linhas em {len(res.abas)} abas -> {args.saida}  ({len(res.avisos)} avisos)')
        return 0

    produtos, variacoes, extras, rel, erros = carga.montar(res, args.incluir_antiga, args.marca)
    rel = [('aviso da limpeza', f'{av[0]} linha {av[1]}', f'{av[2]} | {av[3]}') for av in res.avisos] + rel
    carga.gravar_csv(args.saida_dir, produtos, variacoes, extras, rel)
    print(f'produto: {len(produtos)} | variacao_produto: {len(variacoes)} | avisos da limpeza: {len(res.avisos)} | itens no relatório: {len(rel)}')
    if erros:
        print('ERROS DE VALIDAÇÃO (nada foi gravado no banco):')
        for e in erros:
            print('  -', e)
        return 1
    if args.aplicar:
        url = os.environ.get('DATABASE_URL')
        if not url:
            print('Defina DATABASE_URL para usar --aplicar.')
            return 2
        print(carga.aplicar(produtos, variacoes, url))
    else:
        print(f'Arquivos em {args.saida_dir}/ (nada foi gravado no banco; use --aplicar para gravar).')
    return 0


if __name__ == '__main__':
    sys.exit(main())
