"""Gera os embeddings das pecas para a busca semantica do assistente do cliente.

Vetoriza com o Gemini (`gemini-embedding-2`, 768 dimensoes) o nome, a marca, a categoria, a
colecao, o tipo, o tecido, as cores e a nota de cada peca ativa e grava em `produto.embedding`. So
pega peca sem embedding ou editada depois dele; `--todas` refaz tudo (ao trocar texto ou modelo).

Sem `--aplicar` so conta quantas pecas seriam vetorizadas (nao chama o Gemini nem grava). Rode de
novo depois de importar ou editar pecas no catalogo.

    PYTHONPATH=. python scripts/gerar_embeddings_produtos.py              # conta
    PYTHONPATH=. python scripts/gerar_embeddings_produtos.py --aplicar    # vetoriza e grava
"""

import argparse
import sys

from app.assistente.cliente.embeddings import EmbeddingsGemini, gerar, pecas_pendentes
from app.core.config import Settings
from app.core.db import abrir_conexao


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--aplicar", action="store_true", help="vetoriza e grava")
    parser.add_argument("--todas", action="store_true", help="refaz tambem as que ja tem embedding")
    parser.add_argument("--lote", type=int, default=20, help="pecas por chamada (padrao 20)")
    parser.add_argument("--pausa", type=float, default=15, help="segundos entre lotes (padrao 15)")
    args = parser.parse_args()

    configuracoes = Settings()
    with abrir_conexao(configuracoes) as conexao:
        pecas = pecas_pendentes(conexao, todas=args.todas)
        print(f"pecas a vetorizar: {len(pecas)}")
        if not args.aplicar or not pecas:
            conexao.rollback()
            print("(simulacao: nada foi gravado)" if not args.aplicar else "nada a fazer")
            return
        chave = configuracoes.gemini_api_key
        if not chave or not chave.get_secret_value().strip():
            sys.exit("GEMINI_API_KEY nao configurada")
        feitas = gerar(
            conexao,
            EmbeddingsGemini(chave.get_secret_value()),
            pecas,
            aplicar=True,
            tamanho_do_lote=args.lote,
            pausa=args.pausa,
        )
        print(f"embeddings gravados: {feitas}")


if __name__ == "__main__":
    main()
