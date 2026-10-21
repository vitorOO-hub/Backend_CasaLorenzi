"""Uso:
  python -m clientes_vulto limpar planilha.xlsx --banco vulto.db --saida clientes_padronizado.xlsx
      [--referencia AAAA-MM-DD]   dia em que os pontos são contados (padrão: hoje)
  python -m clientes_vulto carregar planilha.xlsx --banco vulto.db --saida-dir saida_carga
      (só gera CSVs e relatório; com DATABASE_URL, também confere o banco sem gravar)
  python -m clientes_vulto carregar ... --aplicar   (grava no banco; usa DATABASE_URL)
"""
import argparse
import os
from datetime import date, datetime

from . import carga, exporta, limpeza
from .regras import SP


def main(argv=None):
    ap = argparse.ArgumentParser(prog='clientes_vulto')
    sub = ap.add_subparsers(dest='cmd', required=True)
    a = sub.add_parser('limpar', help='padroniza a planilha de clientes cruzando com o banco antigo')
    a.add_argument('planilha')
    a.add_argument('--banco', required=True, help='vulto.db (SQLite do sistema antigo; só leitura)')
    a.add_argument('--saida', default='clientes_padronizado.xlsx')
    a.add_argument('--referencia', type=date.fromisoformat, default=date.today(),
                   help='dia em que os pontos são contados e vencidos (padrão: hoje)')
    b = sub.add_parser('carregar', help='gera as linhas de usuario, movimento_pontos e resgate_pontos '
                       '(e, com --aplicar, grava no banco)')
    b.add_argument('planilha')
    b.add_argument('--banco', required=True, help='vulto.db (SQLite do sistema antigo; só leitura)')
    b.add_argument('--saida-dir', default='saida_carga')
    b.add_argument('--referencia', type=date.fromisoformat, default=date.today(),
                   help='dia em que os pontos são contados e vencidos (padrão: hoje)')
    b.add_argument('--aplicar', action='store_true', help='grava no Postgres (DATABASE_URL). Sem isso, só gera arquivos.')
    args = ap.parse_args(argv)

    # Fim do dia de referência, em São Paulo: tudo o que aconteceu naquele dia conta.
    referencia = datetime(args.referencia.year, args.referencia.month, args.referencia.day, 23, 59, 59, tzinfo=SP)
    res = limpeza.limpar(args.planilha, args.banco, referencia)
    if args.cmd == 'limpar':
        exporta.gravar_xlsx(args.saida, res)
        clientes = res.abas['Clientes'][1]
        print(f'{len(clientes)} clientes -> {args.saida}  ({len(res.avisos)} avisos)')
        for aviso in res.avisos:
            print('  aviso:', ' | '.join(str(x) for x in aviso))
        return 0

    clientes, extrato, resgates, erros = carga.montar(res)
    rel = [('aviso da limpeza', f'{a[0]} linha {a[1]}', a[2]) for a in res.avisos]
    url = os.environ.get('DATABASE_URL')
    if args.aplicar and not url:
        print('defina DATABASE_URL para usar --aplicar')
        return 1
    if url and not args.aplicar:
        import psycopg
        with psycopg.connect(url) as conn, conn.cursor() as cur:
            cur.execute('SET TRANSACTION READ ONLY')
            _, erros_banco, rel_banco, _ = carga.conferir_no_banco(cur, clientes)
        erros += erros_banco
        rel += rel_banco
    carga.gravar_csv(args.saida_dir, clientes, extrato, resgates, rel)
    print(f'usuario: {len(clientes)} | movimento_pontos: {len(extrato)} | resgate_pontos: {len(resgates)} '
          f'| itens no relatório: {len(rel)} -> {args.saida_dir}')
    if erros:
        print('ERROS DE VALIDAÇÃO (nada foi gravado no banco):')
        for e in erros:
            print('  -', e)
        return 1
    if args.aplicar:
        n, rel_banco = carga.aplicar(clientes, extrato, resgates, url)
        carga.gravar_csv(args.saida_dir, clientes, extrato, resgates, rel + rel_banco)
        print('gravado:', ', '.join(f'{k} {v}' for k, v in n.items()))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
