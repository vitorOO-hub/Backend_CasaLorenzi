"""Lanca na hora os vencimentos de pontos Lorenzi+ de todos os clientes com lote vencido.

O banco ja faz isso sozinho todo dia as 03:00 (pg_cron, migracao 20261024100000) e a leitura do
Lorenzi+ faz para o cliente consultado; este script serve para rodar fora de hora. Nao duplica o
que ja foi lancado.

    PYTHONPATH=. python scripts/lancar_vencimentos_pontos.py            # so mostra o que lancaria
    PYTHONPATH=. python scripts/lancar_vencimentos_pontos.py --aplicar  # grava
"""

import argparse

from sqlalchemy import text

from app.core.config import Settings
from app.core.db import abrir_conexao


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--aplicar", action="store_true", help="grava (sem isso, desfaz no fim)")
    args = parser.parse_args()

    with abrir_conexao(Settings()) as conexao:
        pontos = conexao.execute(text("SELECT public.lancar_vencimentos_pontos_todos()")).scalar()
        if args.aplicar:
            conexao.commit()
        else:
            conexao.rollback()
    print(
        f"{pontos} pontos vencidos lancados"
        + ("" if args.aplicar else " (simulacao: nada foi gravado)")
    )


if __name__ == "__main__":
    main()
