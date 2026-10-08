"""Cria lotes de importacao de exemplo do ERP Vulto (so ambiente de desenvolvimento/demonstracao).

Ainda nao existe uma carga automatica do ERP: a tela de Integracoes mostra o que estiver nas
tabelas `importacao_lote` e `importacao_registro`. Sem isto ela fica vazia. Os lotes sao ficticios.

    python scripts/semear_integracao.py             # mostra o que seria criado, sem alterar nada
    python scripts/semear_integracao.py --aplicar   # cria os lotes e registros

So semeia se `importacao_lote` estiver vazia (use --forcar para semear mesmo assim). Roda mais de
uma vez sem duplicar (os codigos dos lotes sao unicos).
"""

import argparse
import sys
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
from dotenv import dotenv_values

RAIZ = Path(__file__).resolve().parents[1]

# (codigo do lote, dias atras, com erro, [(descricao no ERP, codigo Vulto)])
LOTES = (
    (
        "IMP-2026-014",
        35,
        False,
        [
            ("CAMISA LINHO RAVENA P BRANCA", "VLT-77120"),
            ("BLAZER MODENA 42 GRAFITE", "VLT-77188"),
            ("CALCA ALFAIATARIA 40 AREIA", "VLT-77203"),
        ],
    ),
    (
        "IMP-2026-013",
        42,
        False,
        [("CINTO SIENA U CARAMELO", "VLT-76004"), ("CAMISA OXFORD M AZUL", "VLT-76010")],
    ),
    (
        "IMP-2026-012",
        49,
        True,
        [("MEIA SOCIAL ALGODAO 39", "VLT-75500"), ("GRAVATA SEDA MARINHO", "VLT-75512")],
    ),
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--aplicar", action="store_true", help="grava no banco (padrao: so mostra)")
    ap.add_argument("--forcar", action="store_true", help="semeia mesmo com lotes ja existentes")
    ap.add_argument("--env", default=str(RAIZ / ".env"), help="arquivo .env com DATABASE_URL")
    args = ap.parse_args()

    url = (dotenv_values(args.env).get("DATABASE_URL") or "").strip()
    if not url:
        print("DATABASE_URL nao encontrada em", args.env)
        return 1
    print("Banco:", urlsplit(url).hostname)
    total = sum(len(registros) for *_, registros in LOTES)
    print(f"{len(LOTES)} lotes e {total} registros de exemplo.")
    if not args.aplicar:
        print("Nada foi alterado. Use --aplicar para criar.")
        return 0

    with psycopg.connect(url, connect_timeout=15) as conn:
        existentes = conn.execute("SELECT count(*) FROM importacao_lote").fetchone()[0]
        if existentes and not args.forcar:
            print(
                f"Ja existem {existentes} lotes: nada a fazer (use --forcar para semear de novo)."
            )
            return 0
        for codigo, dias, com_erro, registros in LOTES:
            id_lote = conn.execute(
                "INSERT INTO importacao_lote (codigo, com_erro, recebido_em) "
                "VALUES (%s, %s, now() - make_interval(days => %s)) "
                "ON CONFLICT (codigo) DO NOTHING RETURNING id_lote",
                (codigo, com_erro, dias),
            ).fetchone()
            if id_lote is None:
                continue
            for descricao, codigo_externo in registros:
                conn.execute(
                    "INSERT INTO importacao_registro (id_lote, descricao_externa, codigo_externo) "
                    "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                    (id_lote[0], descricao, codigo_externo),
                )
        conn.commit()
    print("Pronto.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
