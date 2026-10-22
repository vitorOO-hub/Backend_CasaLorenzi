"""Gera plano de importacao Vulto em modo seco, sem conexao com o Supabase."""

import argparse
import csv
import hashlib
import json
from pathlib import Path

from openpyxl import load_workbook

from vulto_integracao.plano_importacao import planejar_importacao


def _linhas_planilha(caminho: Path, aba: str) -> list[dict[str, object]]:
    workbook = load_workbook(caminho, read_only=True, data_only=True)
    try:
        linhas = workbook[aba].iter_rows(values_only=True)
        cabecalhos = next(linhas, None)
        if not cabecalhos:
            return []
        return [dict(zip(cabecalhos, valores)) for valores in linhas]
    finally:
        workbook.close()


def _linhas_csv(caminho: Path) -> list[dict[str, str]]:
    with caminho.open(encoding="utf-8-sig", newline="") as arquivo:
        return list(csv.DictReader(arquivo))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("planilha", type=Path)
    parser.add_argument("referencias", type=Path, help="Diretorio com os CSVs exportados")
    parser.add_argument(
        "--saida",
        type=Path,
        help="JSON detalhado do plano; pode conter dados pessoais, proteja o arquivo",
    )
    args = parser.parse_args()

    digest = hashlib.sha256()
    with args.planilha.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1024 * 1024), b""):
            digest.update(bloco)
    codigo_lote = f"VULTO-VENDAS-{digest.hexdigest()[:12].upper()}"

    referencias = args.referencias
    plano = planejar_importacao(
        vendas=_linhas_planilha(args.planilha, "vendas_importacao"),
        itens=_linhas_planilha(args.planilha, "itens_venda_importacao"),
        compras=_linhas_planilha(args.planilha, "compras_importacao"),
        usuarios=_linhas_csv(referencias / "usuario_rows.csv"),
        tipos_usuario=_linhas_csv(referencias / "tipo_usuario_rows.csv"),
        lojas=_linhas_csv(referencias / "loja_rows.csv"),
        status_pedido=_linhas_csv(referencias / "status_pedido_rows.csv"),
        variacoes=_linhas_csv(referencias / "variacao_produto_rows.csv"),
        codigo_lote=codigo_lote,
    )
    resumo = {
        chave: valor
        for chave, valor in plano.items()
        if chave not in {"pedidos", "itens_pedido", "pendencias"}
    }
    print(json.dumps(resumo, ensure_ascii=False, indent=2, default=str))
    if args.saida:
        args.saida.parent.mkdir(parents=True, exist_ok=True)
        args.saida.write_text(json.dumps(plano, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        print(f"Plano detalhado salvo em: {args.saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
