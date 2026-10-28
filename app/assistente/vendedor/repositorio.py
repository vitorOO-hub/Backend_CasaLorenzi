"""Conversas e mensagens dos assistentes (`conversa_assistente`, `mensagem_assistente`).

A conexao da API ignora RLS: toda leitura aqui recebe o `id_usuario` do token e filtra por ele.
"""

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

TIPO_INTERNO = "interno"
TAMANHO_DO_TITULO = 60

# Titulo = comeco da primeira pergunta da conversa (sem coluna nova no banco).
CONVERSA = f"""
SELECT
    c.id_conversa,
    c.status,
    c.criada_em,
    c.atualizada_em,
    COALESCE(
        (SELECT left(m.texto, {TAMANHO_DO_TITULO}) FROM mensagem_assistente m
         WHERE m.id_conversa = c.id_conversa AND m.autor = 'usuario'
         ORDER BY m.criada_em, m.id_mensagem LIMIT 1),
        'Nova conversa'
    ) AS titulo
FROM conversa_assistente c
"""  # nosec B608


def criar_conversa(conexao: Connection, id_usuario: UUID) -> dict[str, Any]:
    id_conversa = conexao.execute(
        text(
            "INSERT INTO conversa_assistente (id_usuario, tipo) "
            "VALUES (CAST(:u AS uuid), :tipo) RETURNING id_conversa"
        ),
        {"u": str(id_usuario), "tipo": TIPO_INTERNO},
    ).scalar_one()
    conexao.commit()
    return conversa_do_usuario(conexao, id_conversa, id_usuario)  # type: ignore[return-value]


def listar_conversas(conexao: Connection, id_usuario: UUID, limite: int) -> list[dict[str, Any]]:
    linhas = conexao.execute(
        text(
            CONVERSA
            + """
            WHERE c.id_usuario = CAST(:u AS uuid) AND c.tipo = :tipo AND c.status <> 'encerrada'
            ORDER BY c.atualizada_em DESC, c.id_conversa
            LIMIT :limite
            """
        ),
        {"u": str(id_usuario), "tipo": TIPO_INTERNO, "limite": limite},
    ).mappings()
    return [dict(linha) for linha in linhas]


def conversa_do_usuario(
    conexao: Connection, id_conversa: UUID, id_usuario: UUID
) -> dict[str, Any] | None:
    """Conversa de outra pessoa volta como inexistente (quem chama responde 404)."""
    linha = (
        conexao.execute(
            text(
                CONVERSA
                + """
                WHERE c.id_conversa = CAST(:c AS uuid) AND c.id_usuario = CAST(:u AS uuid)
                  AND c.tipo = :tipo
                """
            ),
            {"c": str(id_conversa), "u": str(id_usuario), "tipo": TIPO_INTERNO},
        )
        .mappings()
        .first()
    )
    return dict(linha) if linha else None


def mensagens_visiveis(conexao: Connection, id_conversa: UUID) -> list[dict[str, Any]]:
    """Perguntas e respostas (as linhas de ferramenta ficam so na auditoria)."""
    linhas = conexao.execute(
        text(
            """
            SELECT id_mensagem, autor, texto, criada_em,
                   COALESCE(dados -> 'ferramentas', '[]'::jsonb) AS ferramentas,
                   dados ->> 'avaliacao' AS avaliacao
            FROM mensagem_assistente
            WHERE id_conversa = CAST(:c AS uuid) AND autor IN ('usuario', 'assistente')
            ORDER BY criada_em, id_mensagem
            """
        ),
        {"c": str(id_conversa)},
    ).mappings()
    return [dict(linha) for linha in linhas]


def historico(conexao: Connection, id_conversa: UUID, limite: int) -> list[dict[str, Any]]:
    """As ultimas `limite` perguntas e respostas, em ordem cronologica (contexto do modelo)."""
    linhas = conexao.execute(
        text(
            """
            SELECT autor, texto FROM (
                SELECT autor, texto, criada_em, id_mensagem
                FROM mensagem_assistente
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
    texto: str,
    *,
    ferramenta: str | None = None,
    dados: dict[str, Any] | None = None,
    sem_resposta: bool = False,
    modelo: str | None = None,
    tokens_entrada: int | None = None,
    tokens_saida: int | None = None,
) -> dict[str, Any]:
    """Grava na transacao aberta; quem chama faz o commit."""
    return dict(
        conexao.execute(
            text(
                """
                INSERT INTO mensagem_assistente (
                    id_conversa, autor, texto, ferramenta, dados, sem_resposta, modelo,
                    tokens_entrada, tokens_saida, criada_em
                )
                VALUES (
                    CAST(:c AS uuid), :autor, :texto, :ferramenta, CAST(:dados AS jsonb),
                    :sem_resposta, :modelo, :te, :ts, clock_timestamp()
                )
                RETURNING id_mensagem, autor, texto, criada_em,
                          COALESCE(dados -> 'ferramentas', '[]'::jsonb) AS ferramentas
                """
            ),
            {
                "c": str(id_conversa),
                "autor": autor,
                "texto": texto,
                "ferramenta": ferramenta,
                "dados": json.dumps(dados, ensure_ascii=False, default=str) if dados else None,
                "sem_resposta": sem_resposta,
                "modelo": modelo,
                "te": tokens_entrada,
                "ts": tokens_saida,
            },
        )
        .mappings()
        .one()
    )


def tocar_conversa(conexao: Connection, id_conversa: UUID) -> None:
    conexao.execute(
        text(
            "UPDATE conversa_assistente SET atualizada_em = now() "
            "WHERE id_conversa = CAST(:c AS uuid)"
        ),
        {"c": str(id_conversa)},
    )


def mudar_status(conexao: Connection, id_conversa: UUID, status: str) -> None:
    conexao.execute(
        text(
            "UPDATE conversa_assistente SET status = :s, atualizada_em = now() "
            "WHERE id_conversa = CAST(:c AS uuid)"
        ),
        {"c": str(id_conversa), "s": status},
    )
    conexao.commit()


def avaliar_resposta(
    conexao: Connection, id_conversa: UUID, id_mensagem: UUID, avaliacao: str | None
) -> bool:
    """Avaliacao do vendedor (util/nao_util) numa resposta, em `dados` junto da auditoria.
    Devolve False se a mensagem nao e uma resposta desta conversa."""
    alteradas = conexao.execute(
        text(
            """
            UPDATE mensagem_assistente
            SET dados = CASE
                WHEN CAST(:a AS text) IS NULL THEN COALESCE(dados, '{}'::jsonb) - 'avaliacao'
                ELSE COALESCE(dados, '{}'::jsonb)
                     || jsonb_build_object('avaliacao', CAST(:a AS text))
            END
            WHERE id_mensagem = CAST(:m AS uuid) AND id_conversa = CAST(:c AS uuid)
              AND autor = 'assistente'
            """
        ),
        {"m": str(id_mensagem), "c": str(id_conversa), "a": avaliacao},
    ).rowcount
    conexao.commit()
    return alteradas == 1


def perguntas_de_hoje(conexao: Connection, id_usuario: UUID) -> int:
    """Perguntas da pessoa desde a meia-noite de Sao Paulo, em todas as conversas dela."""
    return int(
        conexao.execute(
            text(
                """
                SELECT count(*) FROM mensagem_assistente m
                JOIN conversa_assistente c ON c.id_conversa = m.id_conversa
                WHERE c.id_usuario = CAST(:u AS uuid) AND m.autor = 'usuario'
                  AND m.criada_em >= (date_trunc('day', now() AT TIME ZONE 'America/Sao_Paulo')
                                      AT TIME ZONE 'America/Sao_Paulo')
                """
            ),
            {"u": str(id_usuario)},
        ).scalar_one()
    )
