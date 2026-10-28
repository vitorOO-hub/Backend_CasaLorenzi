"""Persistencia privada das conversas do assistente administrativo."""

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

LIMITE_DIARIO = 25
LIMITE_HISTORICO = 8


class LimiteDiarioAtingido(Exception):
    pass


class ConversaNaoEncontrada(Exception):
    pass


def id_usuario_ativo(conexao: Connection, id_auth: UUID) -> UUID | None:
    return conexao.execute(
        text("SELECT id_usuario FROM usuario WHERE auth_user_id = CAST(:id AS uuid) AND ativo"),
        {"id": str(id_auth)},
    ).scalar_one_or_none()


def criar_conversa(conexao: Connection, id_usuario: UUID, titulo: str | None) -> dict[str, Any]:
    linha = (
        conexao.execute(
            text(
                """
                INSERT INTO conversa_assistente (id_usuario, tipo, status, resumo)
                VALUES (CAST(:usuario AS uuid), 'interno', 'ativa', :titulo)
                RETURNING id_conversa, resumo AS titulo, criada_em, atualizada_em
                """
            ),
            {"usuario": str(id_usuario), "titulo": titulo},
        )
        .mappings()
        .one()
    )
    conexao.commit()

    return dict(linha)


def listar_conversas(conexao: Connection, id_usuario: UUID) -> list[dict[str, Any]]:
    linhas = conexao.execute(
        text(
            """
            SELECT id_conversa, resumo AS titulo, criada_em, atualizada_em
            FROM conversa_assistente
            WHERE id_usuario = CAST(:usuario AS uuid) AND tipo = 'interno'
            ORDER BY atualizada_em DESC
            LIMIT 50
            """
        ),
        {"usuario": str(id_usuario)},
    ).mappings()
    return [dict(linha) for linha in linhas]


def carregar_conversa(
    conexao: Connection, id_conversa: UUID, id_usuario: UUID
) -> dict[str, Any] | None:
    conversa = (
        conexao.execute(
            text(
                """
                SELECT id_conversa, resumo AS titulo, criada_em, atualizada_em
                FROM conversa_assistente
                WHERE id_conversa = CAST(:conversa AS uuid)
                  AND id_usuario = CAST(:usuario AS uuid) AND tipo = 'interno'
                """
            ),
            {"conversa": str(id_conversa), "usuario": str(id_usuario)},
        )
        .mappings()
        .first()
    )
    if conversa is None:
        return None
    mensagens = conexao.execute(
        text(
            """
            SELECT autor, texto, criada_em, modelo
            FROM mensagem_assistente
            WHERE id_conversa = CAST(:conversa AS uuid) AND autor IN ('usuario', 'assistente')
            ORDER BY criada_em DESC, id_mensagem DESC
            LIMIT 100
            """
        ),
        {"conversa": str(id_conversa)},
    ).mappings()
    return {**dict(conversa), "mensagens": [dict(m) for m in reversed(list(mensagens))]}


def historico_para_modelo(conexao: Connection, id_conversa: UUID) -> list[dict[str, str]]:
    mensagens = conexao.execute(
        text(
            """
            SELECT autor, texto FROM (
                SELECT autor, texto, criada_em, id_mensagem
                FROM mensagem_assistente
                WHERE id_conversa = CAST(:conversa AS uuid)
                  AND autor IN ('usuario', 'assistente')
                ORDER BY criada_em DESC, id_mensagem DESC
                LIMIT :limite
            ) recentes
            ORDER BY criada_em, id_mensagem
            """
        ),
        {"conversa": str(id_conversa), "limite": LIMITE_HISTORICO},
    ).mappings()
    return [
        {"role": "assistant" if m["autor"] == "assistente" else "user", "content": m["texto"]}
        for m in mensagens
    ]


def _gravar(
    conexao: Connection,
    *,
    id_conversa: UUID,
    autor: str,
    texto: str,
    ferramenta: str | None = None,
    dados: Any = None,
    modelo: str | None = None,
    tokens_entrada: int | None = None,
    tokens_saida: int | None = None,
) -> None:
    conexao.execute(
        text(
            """
            INSERT INTO mensagem_assistente
                (id_conversa, autor, texto, ferramenta, dados, modelo, tokens_entrada, tokens_saida)
            VALUES (CAST(:conversa AS uuid), :autor, :texto, :ferramenta,
                    CAST(:dados AS jsonb), :modelo, :entrada, :saida)
            """
        ),
        {
            "conversa": str(id_conversa),
            "autor": autor,
            "texto": texto,
            "ferramenta": ferramenta,
            "dados": (
                json.dumps(dados, ensure_ascii=False, default=str) if dados is not None else None
            ),
            "modelo": modelo,
            "entrada": tokens_entrada,
            "saida": tokens_saida,
        },
    )
    conexao.execute(
        text(
            "UPDATE conversa_assistente SET atualizada_em = now() "
            "WHERE id_conversa = CAST(:id AS uuid)"
        ),
        {"id": str(id_conversa)},
    )


def gravar_pergunta(
    conexao: Connection, id_conversa: UUID, id_usuario: UUID, texto: str
) -> list[dict[str, str]]:
    # Serializa a verificação para que chamadas simultâneas não passem juntas pelo limite diário.
    conexao.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(CAST(:usuario AS text), 0))"),
        {"usuario": str(id_usuario)},
    )
    pertence = conexao.execute(
        text(
            """
            SELECT 1 FROM conversa_assistente
            WHERE id_conversa = CAST(:conversa AS uuid)
              AND id_usuario = CAST(:usuario AS uuid) AND tipo = 'interno' AND status = 'ativa'
            FOR UPDATE
            """
        ),
        {"conversa": str(id_conversa), "usuario": str(id_usuario)},
    ).first()
    if pertence is None:
        conexao.rollback()
        raise ConversaNaoEncontrada()
    inicio_dia = conexao.execute(
        text(
            """
            SELECT date_trunc('day', timezone('America/Sao_Paulo', now()))
                   AT TIME ZONE 'America/Sao_Paulo'
            """
        )
    ).scalar_one()
    contagem = conexao.execute(
        text(
            """
            SELECT count(*) FROM mensagem_assistente m
            JOIN conversa_assistente c USING (id_conversa)
            WHERE c.id_usuario = CAST(:usuario AS uuid) AND c.tipo = 'interno'
              AND m.autor = 'usuario' AND m.criada_em >= :inicio
            """
        ),
        {"usuario": str(id_usuario), "inicio": inicio_dia},
    ).scalar_one()
    if contagem >= LIMITE_DIARIO:
        conexao.rollback()
        raise LimiteDiarioAtingido()
    _gravar(conexao, id_conversa=id_conversa, autor="usuario", texto=texto)
    conexao.execute(
        text(
            """
            UPDATE conversa_assistente
            SET resumo = COALESCE(resumo, :titulo)
            WHERE id_conversa = CAST(:conversa AS uuid)
            """
        ),
        {"conversa": str(id_conversa), "titulo": texto[:100]},
    )
    historico = historico_para_modelo(conexao, id_conversa)
    conexao.commit()
    return historico


def gravar_ferramenta(
    conexao: Connection,
    id_conversa: UUID,
    nome: str,
    argumentos: dict[str, Any],
    resultado: Any,
) -> None:
    _gravar(
        conexao,
        id_conversa=id_conversa,
        autor="ferramenta",
        texto="Consulta administrativa executada",
        ferramenta=nome,
        dados={"argumentos": argumentos, "resultado": resultado},
    )
    conexao.commit()


def gravar_resposta(
    conexao: Connection,
    id_conversa: UUID,
    texto: str,
    modelo: str,
    tokens_entrada: int,
    tokens_saida: int,
) -> None:
    _gravar(
        conexao,
        id_conversa=id_conversa,
        autor="assistente",
        texto=texto,
        modelo=modelo,
        tokens_entrada=tokens_entrada,
        tokens_saida=tokens_saida,
    )
    conexao.commit()


def marcar_pergunta_sem_resposta(conexao: Connection, id_conversa: UUID) -> None:
    conexao.execute(
        text(
            """
            UPDATE mensagem_assistente SET sem_resposta = true
            WHERE id_mensagem = (
                SELECT id_mensagem FROM mensagem_assistente
                WHERE id_conversa = CAST(:id AS uuid) AND autor = 'usuario'
                ORDER BY criada_em DESC, id_mensagem DESC LIMIT 1
            )
            """
        ),
        {"id": str(id_conversa)},
    )
    conexao.commit()
