"""Lanca os vencimentos de pontos Vulto+ de todos os clientes com lote vencido.

A leitura do Vulto+ (portal e ficha do painel) ja lanca os vencimentos do cliente consultado; este
script deixa todo mundo em dia, inclusive o saldo da lista de clientes. Pode rodar todo dia: ele
nao duplica o que ja foi lancado.

    PYTHONPATH=. python scripts/lancar_vencimentos_pontos.py            # so mostra o que lancaria
    PYTHONPATH=. python scripts/lancar_vencimentos_pontos.py --aplicar  # grava
"""

import argparse
from datetime import UTC, datetime

from sqlalchemy import text

from app.cliente.vencimento_pontos import CORTE_DA_CARGA, lancar_vencimentos
from app.core.config import Settings
from app.core.db import abrir_conexao


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--aplicar", action="store_true", help="grava (sem isso, desfaz no fim)")
    args = parser.parse_args()

    agora = datetime.now(UTC)
    with abrir_conexao(Settings()) as conexao:
        clientes = (
            conexao.execute(
                text(
                    """
                SELECT DISTINCT id_usuario FROM movimento_pontos
                WHERE vence_em > :corte AND vence_em <= :agora
                """
                ),
                {"corte": CORTE_DA_CARGA, "agora": agora},
            )
            .scalars()
            .all()
        )
        antes = conexao.execute(
            text(
                "SELECT count(*), COALESCE(sum(pontos), 0) FROM movimento_pontos "
                "WHERE tipo = 'vencimento' AND ocorrido_em > :corte"
            ),
            {"corte": CORTE_DA_CARGA},
        ).one()
        for id_cliente in clientes:
            lancar_vencimentos(conexao, id_cliente, agora)
            if args.aplicar:
                conexao.commit()  # um cliente por vez: a trava de cada um dura pouco
        depois = conexao.execute(
            text(
                "SELECT count(*), COALESCE(sum(pontos), 0) FROM movimento_pontos "
                "WHERE tipo = 'vencimento' AND ocorrido_em > :corte"
            ),
            {"corte": CORTE_DA_CARGA},
        ).one()
        if not args.aplicar:
            conexao.rollback()
    print(
        f"{len(clientes)} clientes com lote vencido; "
        f"{depois[0] - antes[0]} vencimentos novos somando {-(depois[1] - antes[1])} pontos"
        + ("" if args.aplicar else " (simulacao: nada foi gravado)")
    )


if __name__ == "__main__":
    main()
