"""SQL do assistente: conversas, mensagens e a busca de produto por texto.

A conexao da API ignora RLS, entao toda leitura e escrita de conversa confere o dono
(`conversa_assistente.id_usuario`) contra o usuario do token.
"""

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection


def criar_conversa(conexao: Connection, id_usuario: UUID, tipo: str) -> dict[str, Any]:
    linha = (
        conexao.execute(
            text(
                """
                INSERT INTO conversa_assistente (id_usuario, tipo)
                VALUES (CAST(:u AS uuid), :tipo)
                RETURNING id_conversa, tipo, status, id_atendimento, criada_em
                """
            ),
            {"u": str(id_usuario), "tipo": tipo},
        )
        .mappings()
        .one()
    )
    return dict(linha)


def obter_conversa(
    conexao: Connection, id_conversa: UUID, id_usuario: UUID, *, travar: bool = False
) -> dict[str, Any] | None:
    linha = (
        conexao.execute(
            text(
                f"""
                SELECT id_conversa, tipo, status, id_atendimento, criada_em
                FROM conversa_assistente
                WHERE id_conversa = CAST(:c AS uuid) AND id_usuario = CAST(:u AS uuid)
                {"FOR UPDATE" if travar else ""}
                """  # nosec B608
            ),
            {"c": str(id_conversa), "u": str(id_usuario)},
        )
        .mappings()
        .first()
    )
    return dict(linha) if linha else None


def mensagens_visiveis(conexao: Connection, id_conversa: UUID, limite: int) -> list[dict[str, Any]]:
    """Ultimas mensagens de pessoa e assistente, em ordem (registro de ferramenta nao aparece)."""
    linhas = conexao.execute(
        text(
            """
            SELECT autor, texto, criada_em FROM (
                SELECT autor, texto, criada_em, id_mensagem FROM mensagem_assistente
                WHERE id_conversa = CAST(:c AS uuid) AND autor IN ('usuario', 'assistente')
                ORDER BY criada_em DESC, id_mensagem DESC
                LIMIT :limite
            ) ultimas
            ORDER BY criada_em, id_mensagem
            """
        ),
        {"c": str(id_conversa), "limite": limite},
    ).mappings()
    return [dict(linha) for linha in linhas]


def gravar_mensagem(
    conexao: Connection,
    id_conversa: UUID,
    autor: str,
    texto_: str = "",
    *,
    ferramenta: str | None = None,
    dados: dict[str, Any] | None = None,
    sem_resposta: bool = False,
    modelo: str | None = None,
    tokens_entrada: int | None = None,
    tokens_saida: int | None = None,
) -> None:
    conexao.execute(
        text(
            """
            INSERT INTO mensagem_assistente (id_conversa, autor, texto, ferramenta, dados,
                sem_resposta, modelo, tokens_entrada, tokens_saida, criada_em)
            VALUES (CAST(:c AS uuid), :autor, :texto, :ferramenta, CAST(:dados AS jsonb),
                :sem_resposta, :modelo, :te, :ts, clock_timestamp())
            """
        ),
        {
            "c": str(id_conversa),
            "autor": autor,
            "texto": texto_,
            "ferramenta": ferramenta,
            "dados": json.dumps(dados, ensure_ascii=False, default=str)
            if dados is not None
            else None,
            "sem_resposta": sem_resposta,
            "modelo": modelo,
            "te": tokens_entrada,
            "ts": tokens_saida,
        },
    )
    conexao.execute(
        text(
            "UPDATE conversa_assistente SET atualizada_em = now() "
            "WHERE id_conversa = CAST(:c AS uuid)"
        ),
        {"c": str(id_conversa)},
    )


def mensagens_do_usuario_hoje(conexao: Connection, id_usuario: UUID) -> int:
    """Mensagens que a pessoa mandou ao assistente hoje (dia de Sao Paulo), em qualquer conversa."""
    return int(
        conexao.execute(
            text(
                """
                SELECT count(*) FROM mensagem_assistente m
                JOIN conversa_assistente c ON c.id_conversa = m.id_conversa
                WHERE c.id_usuario = CAST(:u AS uuid) AND m.autor = 'usuario'
                  AND m.dados->>'origem' IS DISTINCT FROM 'visitante'
                  AND m.criada_em >= date_trunc('day', now() AT TIME ZONE 'America/Sao_Paulo')
                                     AT TIME ZONE 'America/Sao_Paulo'
                """
            ),
            {"u": str(id_usuario)},
        ).scalar_one()
    )


def passar_para_atendente(conexao: Connection, id_conversa: UUID, id_atendimento: UUID) -> None:
    conexao.execute(
        text(
            """
            UPDATE conversa_assistente
            SET status = 'com_atendente', id_atendimento = CAST(:a AS uuid), atualizada_em = now()
            WHERE id_conversa = CAST(:c AS uuid)
            """
        ),
        {"c": str(id_conversa), "a": str(id_atendimento)},
    )


def _sem_acento(expressao: str) -> str:
    """Minusculas e sem acento, no SQL ("Calça" e "calca" casam)."""
    return f"translate(lower({expressao}), 'áàâãäéèêëíìîïóòôõöúùûüç', 'aaaaaeeeeiiiiooooouuuuc')"


def buscar_produtos(conexao: Connection, termos: list[str], limite: int) -> list[dict[str, Any]]:
    """Pecas ativas com estoque cujo nome, categoria, marca, tecido ou cor contem todos os termos.

    Busca por texto enquanto os embeddings (`produto.embedding`) nao sao gerados.
    """
    alvo = _sem_acento("concat_ws(' ', p.nome, p.categoria, p.marca, p.tecido, p.cores::text)")
    filtros = " AND ".join(
        f"{alvo} LIKE '%' || {_sem_acento(f'CAST(:t{i} AS text)')} || '%'"
        for i in range(len(termos))
    )
    parametros: dict[str, Any] = {f"t{i}": termo for i, termo in enumerate(termos)}
    parametros["limite"] = limite
    linhas = conexao.execute(
        text(
            f"""
            SELECT p.nome, p.categoria, p.marca, p.preco_base,
                   json_agg(json_build_object('sku', v.sku, 'cor', v.cor, 'tamanho', v.tamanho,
                                              'preco', v.preco_venda) ORDER BY v.sku) AS variacoes
            FROM produto p
            JOIN variacao_produto v ON v.id_produto = p.id_produto AND v.ativa
            WHERE p.ativo AND {filtros}
              AND EXISTS (
                  SELECT 1 FROM estoque e JOIN loja l ON l.id_loja = e.id_loja AND l.ativa
                  WHERE e.id_variacao = v.id_variacao AND e.quantidade > 0
              )
            GROUP BY p.id_produto, p.nome, p.categoria, p.marca, p.preco_base
            ORDER BY p.nome
            LIMIT :limite
            """  # nosec B608
        ),
        parametros,
    ).mappings()
    return [dict(linha) for linha in linhas]


def variacao_ativa_pelo_sku(conexao: Connection, sku: str) -> UUID | None:
    return conexao.execute(
        text(
            """
            SELECT v.id_variacao
            FROM variacao_produto v JOIN produto p ON p.id_produto = v.id_produto
            WHERE upper(v.sku) = upper(:sku) AND v.ativa AND p.ativo
            """
        ),
        {"sku": sku},
    ).scalar()
