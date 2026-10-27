"""Consultas das automacoes. A conexao ignora RLS: so devolvem o que o n8n precisa para avisar."""

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.cliente.repositorio import SALDO_E_CREDITOS_NO_ANO

# Cliente ativo que aceita mensagens, com o contato do canal preenchido.
CONTATOS = f"""
SELECT u.id_usuario, u.nome, u.email, u.telefone, {SALDO_E_CREDITOS_NO_ANO}
FROM usuario u
JOIN tipo_usuario t ON t.id_tipo_usuario = u.id_tipo_usuario AND t.codigo = 'cliente'
LEFT JOIN movimento_pontos m ON m.id_usuario = u.id_usuario
WHERE u.id_usuario = ANY(CAST(:ids AS uuid[]))
  AND u.ativo
  AND u.aceita_mensagens
  AND CASE CAST(:canal AS text)
          WHEN 'email' THEN COALESCE(u.email, '') <> ''
          ELSE COALESCE(u.telefone, '') <> ''
      END
GROUP BY u.id_usuario
ORDER BY u.nome
"""  # nosec B608


def contatos(conexao: Connection, ids: list[UUID], canal: str) -> list[dict[str, Any]]:
    if not ids:
        return []
    linhas = conexao.execute(
        text(CONTATOS), {"ids": [str(i) for i in ids], "canal": canal}
    ).mappings()
    return [dict(linha) for linha in linhas]


def avisados(conexao: Connection, ids: list[UUID], canal: str) -> set[tuple[UUID, Any]]:
    if not ids:
        return set()
    linhas = conexao.execute(
        text(
            """
            SELECT id_usuario, vence_em FROM aviso_pontos
            WHERE canal = :canal AND id_usuario = ANY(CAST(:ids AS uuid[]))
            """
        ),
        {"ids": [str(i) for i in ids], "canal": canal},
    ).all()
    return {(linha.id_usuario, linha.vence_em) for linha in linhas}


def gravar_avisos(conexao: Connection, canal: str, avisos: str) -> int:
    """`avisos` e um JSON (lista de {id_cliente, vence_em, pontos}). Repetido e ignorado; cliente
    inexistente tambem (o JOIN descarta), em vez de derrubar o lote inteiro."""
    gravados = conexao.execute(
        text(
            """
            INSERT INTO aviso_pontos (id_usuario, vence_em, pontos, canal)
            SELECT a.id_cliente, a.vence_em, a.pontos, :canal
            FROM jsonb_to_recordset(CAST(:avisos AS jsonb))
                 AS a(id_cliente uuid, vence_em timestamptz, pontos int)
            JOIN usuario u ON u.id_usuario = a.id_cliente
            ON CONFLICT (id_usuario, vence_em, canal) DO NOTHING
            """
        ),
        {"canal": canal, "avisos": avisos},
    ).rowcount
    conexao.commit()
    return gravados


def nomes_das_lojas(conexao: Connection) -> dict[UUID, str]:
    return dict(conexao.execute(text("SELECT id_loja, nome FROM loja")).all())
