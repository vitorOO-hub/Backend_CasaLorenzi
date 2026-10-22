"""Gera uma pre-validacao sem PII e sem gravar no banco para a carga de vendas do Vulto."""

import argparse
import json
from pathlib import Path

from vulto_integracao.preflight_vendas import preflight_vendas


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("arquivo", type=Path, help="Planilha consolidada do Vulto")
    parser.add_argument("--saida", type=Path, help="Salva o resumo JSON neste caminho")
    args = parser.parse_args()

    relatorio = preflight_vendas(args.arquivo)
    texto = json.dumps(relatorio, ensure_ascii=False, indent=2)
    print(texto)
    if args.saida:
        args.saida.write_text(texto + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
