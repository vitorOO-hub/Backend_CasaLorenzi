"""Gera embeddings do catalogo ativo; simula por padrao, use --aplicar para gravar."""

import argparse

from sqlalchemy import text

from app.assistente import embeddings
from app.core.config import Settings
from app.core.db import abrir_conexao

PRODUTOS_PENDENTES = text(
    """
    SELECT id_produto, nome, marca, categoria, colecao, tipo, cores, tecido,
           tecelagem, costurado_em, nota
    FROM public.produto
    WHERE ativo AND (embedding IS NULL OR embedding_em IS NULL
                     OR atualizado_em > embedding_em)
    ORDER BY atualizado_em, id_produto
    LIMIT :limite
    """
)

ATUALIZAR = text(
    """
    UPDATE public.produto
    SET embedding = CAST(:embedding AS extensions.vector), embedding_em = now()
    WHERE id_produto = :id_produto AND ativo
    """
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--aplicar", action="store_true", help="chama Gemini e grava os vetores")
    parser.add_argument("--limite", type=int, default=100, help="maximo de produtos por execucao")
    args = parser.parse_args()
    if args.limite < 1 or args.limite > 1000:
        parser.error("--limite deve estar entre 1 e 1000")

    configuracoes = Settings()
    with abrir_conexao(configuracoes) as conexao:
        produtos = [dict(linha) for linha in conexao.execute(
            PRODUTOS_PENDENTES, {"limite": args.limite}
        ).mappings()]
        conexao.rollback()

        print(f"Produtos selecionados para indexar (limite {args.limite}): {len(produtos)}")
        if not args.aplicar:
            print("Simulacao: nada foi enviado ao Gemini nem gravado. Use --aplicar para executar.")
            return
        if configuracoes.gemini_api_key is None:
            parser.error("GEMINI_API_KEY nao esta configurada")

        atualizados = []
        for produto in produtos:
            vetor = embeddings.gerar(
                embeddings.texto_produto(produto), configuracoes.gemini_api_key
            )
            atualizados.append((produto["id_produto"], embeddings.serializar(vetor)))
        try:
            for id_produto, vetor in atualizados:
                conexao.execute(
                    ATUALIZAR,
                    {"embedding": vetor, "id_produto": id_produto},
                )
            conexao.commit()
        except Exception:
            conexao.rollback()
            raise
        print(f"Embeddings atualizados: {len(atualizados)}")


if __name__ == "__main__":
    main()
