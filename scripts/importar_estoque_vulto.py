"""Importa estoque historico Vulto no Supabase apos confirmacao explicita."""

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

from scripts.vulto_integracao.estoque import carregar_e_gravar
from scripts.vulto_integracao.importador import ImportacaoVultoError, validar_dsn_producao_supabase

NOME_PLANILHA = Path(
    "Vulto/vulto-legado-back-vitor/data/vulto_db_migracao_consolidada_com_amigo.xlsx"
)


def _planilha_padrao() -> Path:
    for raiz in Path(__file__).resolve().parents:
        candidata = raiz / NOME_PLANILHA
        if candidata.is_file():
            return candidata
    return Path(__file__).resolve().parents[1] / NOME_PLANILHA


PLANILHA_PADRAO = _planilha_padrao()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--planilha", type=Path, default=PLANILHA_PADRAO)
    parser.add_argument("--aplicar-producao", action="store_true")
    parser.add_argument("--confirmar-producao", action="store_true")
    args = parser.parse_args()

    if not args.aplicar_producao or not args.confirmar_producao:
        parser.error(
            "para gravar no Supabase, informe --aplicar-producao --confirmar-producao"
        )
    if not args.planilha.is_file():
        parser.error(f"planilha nao encontrada: {args.planilha}")

    for raiz in Path(__file__).resolve().parents:
        arquivo_env = raiz / ".env"
        if arquivo_env.is_file():
            load_dotenv(arquivo_env)
            break
    dsn = os.environ.get("DATABASE_URL", "")
    try:
        validar_dsn_producao_supabase(dsn)
    except ImportacaoVultoError as erro:
        parser.error(str(erro))

    try:
        import psycopg
    except ImportError as erro:
        parser.error("instale psycopg[binary] antes da importacao")
        raise erro

    with psycopg.connect(dsn) as conexao:
        resultado = carregar_e_gravar(conexao, args.planilha)
    print("Importacao Vulto concluida:")
    for tabela, quantidade in resultado.items():
        print(f"  {tabela}: {quantidade}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
