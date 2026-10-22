"""Valida um plano ou grava-o em teste/producao com confirmacao explicita."""

import argparse
import json
import os
from pathlib import Path

from dotenv import dotenv_values

from vulto_integracao.importador import (
    ImportacaoVultoError,
    gravar_plano,
    validar_dsn_local_teste,
    validar_dsn_producao_supabase,
    validar_plano,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plano", type=Path, help="JSON gerado pelo planejador")
    parser.add_argument("--aplicar", action="store_true", help="Grava no banco de teste")
    parser.add_argument(
        "--aplicar-producao",
        action="store_true",
        help="Grava no Supabase remoto; requer --confirmar-producao",
    )
    parser.add_argument(
        "--confirmar-vulto",
        action="store_true",
        help="Confirma que deseja gravar a importacao Vulto no banco de teste",
    )
    parser.add_argument(
        "--confirmar-producao",
        action="store_true",
        help="Confirma a gravacao do lote Vulto no banco de producao",
    )
    args = parser.parse_args()

    if args.aplicar and args.aplicar_producao:
        parser.error("escolha somente um destino: teste ou producao")
    if args.confirmar_vulto and not args.aplicar:
        parser.error("--confirmar-vulto so pode ser usado com --aplicar")
    if args.confirmar_producao and not args.aplicar_producao:
        parser.error("--confirmar-producao so pode ser usado com --aplicar-producao")

    plano = json.loads(args.plano.read_text(encoding="utf-8"))
    validar_plano(plano)
    if not args.aplicar and not args.aplicar_producao:
        print(
            f"Plano valido: {len(plano['pedidos'])} pedidos e "
            f"{len(plano['itens_pedido'])} itens e "
            f"{len(plano.get('pendencias', []))} pendencias. "
            "Nenhuma conexao ou gravacao realizada."
        )
        return 0
    if args.aplicar and not args.confirmar_vulto:
        parser.error("para gravar, informe --aplicar e --confirmar-vulto")
    if args.aplicar_producao and not args.confirmar_producao:
        parser.error("para gravar em producao, informe --aplicar-producao e --confirmar-producao")

    ambiente = {**dotenv_values(Path(__file__).resolve().parents[1] / ".env"), **os.environ}
    if args.aplicar:
        dsn = ambiente.get("TEST_DATABASE_URL")
        if not dsn:
            parser.error("TEST_DATABASE_URL nao configurada")
        try:
            validar_dsn_local_teste(dsn)
        except ImportacaoVultoError as erro:
            parser.error(str(erro))
    else:
        dsn = ambiente.get("DATABASE_URL")
        if not dsn:
            parser.error("DATABASE_URL nao configurada")
        try:
            validar_dsn_producao_supabase(dsn)
        except ImportacaoVultoError as erro:
            parser.error(str(erro))

    import psycopg

    with psycopg.connect(dsn) as conexao:
        with conexao.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            banco = cursor.fetchone()[0]
        if args.aplicar and not str(banco).endswith("_teste"):
            parser.error("gravacao bloqueada: o banco conectado nao termina com _teste")
        if args.aplicar_producao and str(banco).endswith("_teste"):
            parser.error("gravacao de producao bloqueada: a conexao aponta para banco _teste")
        quantidades = gravar_plano(conexao, plano)
    print(
        f"Importacao {'de teste' if args.aplicar else 'de producao'} concluida: "
        f"{quantidades['pedidos']} pedidos, {quantidades['itens']} itens e "
        f"{quantidades['pendencias']} pendencias."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
