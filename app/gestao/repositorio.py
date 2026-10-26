"""Consultas da gestao do admin, em SQLAlchemy (`text` com parametros ligados).

O time interno e todo `usuario` que nao e cliente. O codigo `diretor` do banco aparece como `admin`
(mesmo nome do papel no token). A conexao da API ignora RLS: quem pode chamar isto e decidido no
router (so admin).
"""

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

EQUIPE = """
SELECT u.id_usuario, u.nome, u.email,
       CASE t.codigo WHEN 'diretor' THEN 'admin' ELSE t.codigo END AS cargo,
       u.id_loja, l.nome AS loja_nome,
       u.ativo, (u.auth_user_id IS NOT NULL) AS com_acesso, u.criado_em
FROM usuario u
JOIN tipo_usuario t ON t.id_tipo_usuario = u.id_tipo_usuario
LEFT JOIN loja l ON l.id_loja = u.id_loja
WHERE t.codigo <> 'cliente'
"""

CARGOS = """
SELECT CASE t.codigo WHEN 'diretor' THEN 'admin' ELSE t.codigo END AS codigo, t.nome
FROM tipo_usuario t
WHERE t.ativo AND t.codigo <> 'cliente'
ORDER BY t.nome
"""


def equipe(conexao: Connection, *, id_loja: UUID | None = None) -> list[dict[str, Any]]:
    filtro = " AND u.id_loja = CAST(:loja AS uuid)" if id_loja else ""
    linhas = conexao.execute(
        text(EQUIPE + filtro + " ORDER BY u.nome, u.email"),
        {"loja": str(id_loja) if id_loja else None},
    ).mappings()
    return [dict(linha) for linha in linhas]


def um_da_equipe(conexao: Connection, id_usuario: UUID) -> dict[str, Any] | None:
    linha = (
        conexao.execute(
            text(EQUIPE + " AND u.id_usuario = CAST(:id AS uuid)"), {"id": str(id_usuario)}
        )
        .mappings()
        .first()
    )
    return dict(linha) if linha else None


def cargos(conexao: Connection, *, gerente: bool = False) -> list[dict[str, Any]]:
    consulta = CARGOS
    if gerente:
        consulta = CARGOS.replace(
            "ORDER BY t.nome",
            "AND t.codigo IN ('atendente', 'operador_estoque', 'vendedor')\nORDER BY t.nome",
        )
    return [dict(linha) for linha in conexao.execute(text(consulta)).mappings()]


def lojas_ativas(conexao: Connection) -> list[dict[str, Any]]:
    linhas = conexao.execute(
        text("SELECT id_loja, nome FROM loja WHERE ativa ORDER BY nome")
    ).mappings()
    return [dict(linha) for linha in linhas]


def email_em_uso(conexao: Connection, email: str) -> bool:
    return bool(
        conexao.execute(
            text("SELECT 1 FROM usuario WHERE lower(email) = :email"), {"email": email}
        ).scalar()
    )


def inserir_usuario(
    conexao: Connection, *, nome: str, email: str, cargo: str, id_loja: UUID | None
) -> UUID | None:
    codigo = "diretor" if cargo == "admin" else cargo
    linha = conexao.execute(
        text(
            """
            INSERT INTO usuario (id_tipo_usuario, id_loja, nome, email, ativo)
            SELECT id_tipo_usuario, CAST(:loja AS uuid), :nome, :email, TRUE
            FROM tipo_usuario WHERE codigo = :codigo AND ativo
            RETURNING id_usuario
            """
        ),
        {
            "loja": str(id_loja) if id_loja else None,
            "nome": nome,
            "email": email,
            "codigo": codigo,
        },
    ).first()
    return linha[0] if linha else None


def ligar_auth(conexao: Connection, id_usuario: UUID, id_auth: UUID) -> bool:
    resultado = conexao.execute(
        text(
            """
            UPDATE usuario SET auth_user_id = CAST(:auth AS uuid), atualizado_em = now()
            WHERE id_usuario = CAST(:id AS uuid) AND auth_user_id IS NULL
            """
        ),
        {"auth": str(id_auth), "id": str(id_usuario)},
    )
    return resultado.rowcount == 1


def travar(conexao: Connection, id_usuario: UUID) -> dict[str, Any] | None:
    """Trava a linha (sem JOIN, o FOR UPDATE nao aceita) e devolve o que decide a mudanca."""
    linha = (
        conexao.execute(
            text(
                """
                SELECT id_usuario, auth_user_id, ativo, id_tipo_usuario
                FROM usuario WHERE id_usuario = CAST(:id AS uuid) FOR UPDATE
                """
            ),
            {"id": str(id_usuario)},
        )
        .mappings()
        .first()
    )
    return dict(linha) if linha else None


def loja_ativa(conexao: Connection, id_loja: UUID) -> bool:
    return bool(
        conexao.execute(
            text("SELECT 1 FROM loja WHERE id_loja = CAST(:id AS uuid) AND ativa"),
            {"id": str(id_loja)},
        ).scalar()
    )


def outros_admins_ativos(conexao: Connection, id_usuario: UUID) -> int:
    return int(
        conexao.execute(
            text(
                """
                SELECT count(*) FROM usuario u
                JOIN tipo_usuario t ON t.id_tipo_usuario = u.id_tipo_usuario
                WHERE t.codigo = 'diretor' AND u.ativo AND t.ativo
                  AND u.id_usuario <> CAST(:id AS uuid)
                """
            ),
            {"id": str(id_usuario)},
        ).scalar_one()
    )


def atualizar(
    conexao: Connection, id_usuario: UUID, *, cargo: str, id_loja: UUID | None, ativo: bool
) -> None:
    codigo = "diretor" if cargo == "admin" else cargo
    conexao.execute(
        text(
            """
            UPDATE usuario
            SET id_tipo_usuario = (SELECT id_tipo_usuario FROM tipo_usuario WHERE codigo = :codigo),
                id_loja = CAST(:loja AS uuid),
                ativo = :ativo,
                atualizado_em = now()
            WHERE id_usuario = CAST(:id AS uuid)
            """
        ),
        {
            "codigo": codigo,
            "loja": str(id_loja) if id_loja else None,
            "ativo": ativo,
            "id": str(id_usuario),
        },
    )
