"""Uso:
  python -m clientes_vulto limpar planilha.xlsx --banco vulto.db --saida clientes_padronizado.xlsx
      [--referencia AAAA-MM-DD]   dia em que os pontos são contados (padrão: hoje)
"""
import argparse
from datetime import date, datetime

from . import exporta, limpeza
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
    args = ap.parse_args(argv)

    # Fim do dia de referência, em São Paulo: tudo o que aconteceu naquele dia conta.
    referencia = datetime(args.referencia.year, args.referencia.month, args.referencia.day, 23, 59, 59, tzinfo=SP)
    res = limpeza.limpar(args.planilha, args.banco, referencia)
    exporta.gravar_xlsx(args.saida, res)
    clientes = res.abas['Clientes'][1]
    print(f'{len(clientes)} clientes -> {args.saida}  ({len(res.avisos)} avisos)')
    for aviso in res.avisos:
        print('  aviso:', ' | '.join(str(x) for x in aviso))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
