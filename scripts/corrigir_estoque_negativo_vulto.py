"""Zera saldos negativos da carga Vulto com ajuste de migracao rastreavel."""

import argparse
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from scripts.vulto_integracao.estoque import (
    CODIGO_LOTE,
    ImportacaoEstoqueError,
    carregar_planilha,
    preparar_snapshot,
)
from scripts.vulto_integracao.importador import (
    ImportacaoVultoError,
    validar_dsn_producao_supabase,
)
from scripts.vulto_integracao.lojas import CODIGO_LOJA_POR_ID_VULTO

ORIGEM_CORRECAO = "vulto_zeramento_saldo_negativo"
NOME_PLANILHA = Path(
    "Vulto/vulto-legado-back-vitor/data/vulto_db_migracao_consolidada_com_amigo.xlsx"
)


def _planilha_padrao() -> Path:
    for raiz in Path(__file__).resolve().parents:
        candidata = raiz / NOME_PLANILHA
        if candidata.is_file():
            return candidata
    return Path(__file__).resolve().parents[1] / NOME_PLANILHA


def _id_origem_ajuste(id_lote: Any, id_loja: Any, sku: str) -> str:
    return f"estoque-negativo-zerado:{id_lote}:{id_loja}:{sku}"


def _ajustes_esperados(cursor: Any, caminho: Path) -> list[dict[str, Any]]:
    fontes = carregar_planilha(caminho)
    codigos = list(CODIGO_LOJA_POR_ID_VULTO.values())
    cursor.execute("SELECT codigo, id_loja FROM public.loja WHERE codigo = ANY(%s)", (codigos,))
    lojas = {codigo: id_loja for codigo, id_loja in cursor.fetchall()}
    if set(lojas) != set(codigos):
        raise ImportacaoEstoqueError("As sete lojas Vulto precisam existir no Supabase")

    snapshot = preparar_snapshot(fontes["estoque_conferencia"], lojas)
    ajustes = []
    for linha in snapshot:
        quantidade_origem = linha["quantidade_origem"]
        if quantidade_origem < 0:
            ajustes.append(
                {
                    "codigo_loja": next(
                        codigo
                        for codigo, id_loja in lojas.items()
                        if id_loja == linha["id_loja"]
                    ),
                    "id_loja": linha["id_loja"],
                    "sku": linha["sku"],
                    "quantidade_origem": quantidade_origem,
                    "atualizado_em_origem": linha["atualizado_em"],
                }
            )
    return ajustes


def corrigir_saldos(conexao: Any, caminho: Path, *, aplicar: bool) -> dict[str, int]:
    from psycopg.types.json import Jsonb

    with conexao.transaction():
        if not aplicar:
            conexao.execute("SET TRANSACTION READ ONLY")
        with conexao.cursor() as cursor:
            if aplicar:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtext('vulto-estoque-importacao'))"
                )
            ajustes = _ajustes_esperados(cursor, caminho)
            if not ajustes:
                return {
                    "saldos_negativos_na_fonte": 0,
                    "ajustes_aplicados": 0,
                    "ajustes_pendentes": 0,
                    "unidades_a_zerar": 0,
                    "unidades_zeradas": 0,
                }

            cursor.execute(
                "SELECT id_lote FROM public.importacao_lote WHERE codigo = %s"
                + (" FOR UPDATE" if aplicar else ""),
                (CODIGO_LOTE,),
            )
            lote = cursor.fetchone()
            if not lote:
                raise ImportacaoEstoqueError(
                    "O lote de estoque Vulto nao existe; esta correcao so trata "
                    "a carga ja importada"
                )
            id_lote = lote[0]
            valores = ", ".join(["(%s, %s)"] * len(ajustes))
            parametros = [
                valor
                for ajuste in ajustes
                for valor in (ajuste["codigo_loja"], ajuste["sku"])
            ]
            cursor.execute(
                f"""
                SELECT l.codigo, l.id_loja, v.sku, v.id_variacao, e.quantidade
                FROM (VALUES {valores}) AS esperados(codigo_loja, sku)
                JOIN public.loja l ON l.codigo = esperados.codigo_loja
                JOIN public.variacao_produto v ON v.sku = esperados.sku
                JOIN public.produto p ON p.id_produto = v.id_produto
                    AND lower(p.marca) = 'vulto'
                JOIN public.estoque e ON e.id_loja = l.id_loja
                    AND e.id_variacao = v.id_variacao
                """ + ("FOR UPDATE OF e" if aplicar else ""),
                parametros,
            )
            atuais = {
                (codigo, sku): {
                    "id_loja": id_loja,
                    "id_variacao": id_variacao,
                    "quantidade": quantidade,
                }
                for codigo, id_loja, sku, id_variacao, quantidade in cursor.fetchall()
            }
            if len(atuais) != len(ajustes):
                raise ImportacaoEstoqueError(
                    "Nem todos os saldos negativos esperados foram encontrados no Supabase"
                )

            cursor.execute(
                """
                SELECT l.codigo, v.sku, e.quantidade
                FROM public.estoque e
                JOIN public.loja l USING (id_loja)
                JOIN public.variacao_produto v USING (id_variacao)
                JOIN public.produto p USING (id_produto)
                WHERE l.codigo = ANY(%s) AND lower(p.marca) = 'vulto'
                  AND e.quantidade < 0
                """ + ("FOR UPDATE OF e" if aplicar else ""),
                (list(CODIGO_LOJA_POR_ID_VULTO.values()),),
            )
            negativos_atuais = {
                (codigo, sku): quantidade for codigo, sku, quantidade in cursor.fetchall()
            }
            negativos_esperados = {}
            for ajuste in ajustes:
                chave = (ajuste["codigo_loja"], ajuste["sku"])
                if atuais[chave]["quantidade"] < 0:
                    negativos_esperados[chave] = ajuste["quantidade_origem"]
            if negativos_atuais != negativos_esperados:
                raise ImportacaoEstoqueError(
                    "Os saldos negativos atuais nao coincidem exatamente com a planilha; "
                    "correcao cancelada"
                )

            ids = [atuais[(a["codigo_loja"], a["sku"])] for a in ajustes]
            cursor.execute(
                f"""
                SELECT count(*)
                FROM public.movimentacao_estoque
                WHERE id_lote IS DISTINCT FROM %s
                  AND (id_loja, id_variacao) IN ({', '.join(['(%s, %s)'] * len(ids))})
                """,
                [
                    id_lote,
                    *[
                        valor
                        for item in ids
                        for valor in (item["id_loja"], item["id_variacao"])
                    ],
                ],
            )
            if cursor.fetchone()[0]:
                raise ImportacaoEstoqueError(
                    "Ha movimentos posteriores/fora do lote em SKUs afetados; revise antes de zerar"
                )

            cursor.execute(
                """
                SELECT id_tipo_movimentacao_estoque, sinal
                FROM public.tipo_movimentacao_estoque
                WHERE codigo = 'ajuste_positivo'
                """
            )
            tipo = cursor.fetchone()
            if not tipo or tipo[1] != 1:
                raise ImportacaoEstoqueError("Tipo ajuste_positivo ausente ou com sinal inesperado")
            id_tipo_ajuste = tipo[0]

            ids_origem = [
                _id_origem_ajuste(
                    id_lote,
                    atuais[(a["codigo_loja"], a["sku"])]["id_loja"],
                    a["sku"],
                )
                for a in ajustes
            ]
            cursor.execute(
                """
                SELECT id_origem_importacao, quantidade, quantidade_anterior,
                       quantidade_posterior
                FROM public.movimentacao_estoque
                WHERE origem_importacao = %s AND id_origem_importacao = ANY(%s)
                """ + ("FOR UPDATE" if aplicar else ""),
                (ORIGEM_CORRECAO, ids_origem),
            )
            movimentos_existentes = {
                id_origem: (quantidade, anterior, posterior)
                for id_origem, quantidade, anterior, posterior in cursor.fetchall()
            }

            pendentes = []
            for ajuste in ajustes:
                chave = (ajuste["codigo_loja"], ajuste["sku"])
                atual = atuais[chave]
                quantidade = ajuste["quantidade_origem"]
                id_origem = _id_origem_ajuste(
                    id_lote, atual["id_loja"], ajuste["sku"]
                )
                movimento_existente = movimentos_existentes.get(id_origem)
                if atual["quantidade"] == 0 and movimento_existente == (
                    abs(quantidade), quantidade, 0
                ):
                    continue
                if atual["quantidade"] != quantidade or movimento_existente:
                    raise ImportacaoEstoqueError(
                        f"Saldo mudou desde a carga para {chave}; correcao cancelada"
                    )
                pendentes.append(ajuste)

            if not aplicar:
                return {
                    "saldos_negativos_na_fonte": len(ajustes),
                    "ajustes_aplicados": 0,
                    "ajustes_pendentes": len(pendentes),
                    "unidades_a_zerar": sum(
                        abs(ajuste["quantidade_origem"]) for ajuste in pendentes
                    ),
                }

            if not pendentes:
                return {
                    "saldos_negativos_na_fonte": len(ajustes),
                    "ajustes_aplicados": 0,
                    "ajustes_pendentes": 0,
                    "unidades_a_zerar": 0,
                }

            agora = conexao.execute("SELECT now()").fetchone()[0]
            alterados = 0
            unidades = 0
            insercoes = []
            atualizacoes = []
            for ajuste in pendentes:
                chave = (ajuste["codigo_loja"], ajuste["sku"])
                atual = atuais[chave]
                quantidade = ajuste["quantidade_origem"]
                id_origem = _id_origem_ajuste(
                    id_lote, atual["id_loja"], ajuste["sku"]
                )
                insercoes.append(
                    (
                        atual["id_loja"],
                        atual["id_variacao"],
                        id_tipo_ajuste,
                        abs(quantidade),
                        quantidade,
                        "Ajuste de migracao aprovado: saldo legado negativo tratado como zero; "
                        "nao representa entrada fisica.",
                        agora,
                        id_lote,
                        ORIGEM_CORRECAO,
                        id_origem,
                        Jsonb(
                            {
                                "regra_migracao": "saldo_final_negativo_igual_zero",
                                "quantidade_legada": quantidade,
                                "codigo_loja_legado": ajuste["codigo_loja"],
                                "sku": ajuste["sku"],
                                "atualizado_em_origem": ajuste[
                                    "atualizado_em_origem"
                                ].isoformat(),
                                "nao_e_entrada_fisica": True,
                            }
                        ),
                    ),
                )
                atualizacoes.append(
                    (agora, atual["id_loja"], atual["id_variacao"], quantidade)
                )
                alterados += 1
                unidades += abs(quantidade)

            cursor.executemany(
                """
                INSERT INTO public.movimentacao_estoque (
                    id_loja, id_variacao, id_tipo_movimentacao_estoque,
                    quantidade, quantidade_anterior, quantidade_posterior,
                    motivo, criada_em, id_lote, origem_importacao,
                    id_origem_importacao, dados_origem
                ) VALUES (%s, %s, %s, %s, %s, 0, %s, %s, %s, %s, %s, %s)
                """,
                insercoes,
            )
            cursor.executemany(
                """
                UPDATE public.estoque SET quantidade = 0, atualizado_em = %s
                WHERE id_loja = %s AND id_variacao = %s AND quantidade = %s
                """,
                atualizacoes,
            )
            if cursor.rowcount != alterados:
                raise ImportacaoEstoqueError(
                    "Um ou mais saldos mudaram durante a correcao; transacao cancelada"
                )

    return {
        "saldos_negativos_na_fonte": len(ajustes),
        "ajustes_aplicados": alterados,
        "ajustes_pendentes": 0,
        "unidades_zeradas": unidades,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--planilha", type=Path, default=_planilha_padrao())
    parser.add_argument("--aplicar-producao", action="store_true")
    parser.add_argument("--confirmar-producao", action="store_true")
    args = parser.parse_args()
    aplicar = args.aplicar_producao and args.confirmar_producao
    if args.aplicar_producao != args.confirmar_producao:
        parser.error("para gravar no Supabase, informe os dois sinalizadores de confirmacao")
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
        parser.error("instale psycopg[binary] antes da correcao")
        raise erro

    with psycopg.connect(dsn) as conexao:
        resultado = corrigir_saldos(conexao, args.planilha, aplicar=aplicar)
    prefixo = "Correcao aplicada" if aplicar else "Previa somente leitura"
    print(f"{prefixo}:")
    for chave, valor in resultado.items():
        print(f"  {chave}: {valor}")
    if not aplicar:
        print("Para gravar, execute com --aplicar-producao --confirmar-producao")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
