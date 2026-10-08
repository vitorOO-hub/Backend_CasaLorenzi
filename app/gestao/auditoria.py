"""Auditoria: quem fez o que. Gravada pelos servicos, na transacao da acao; lida so pelo admin."""

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.erros_auth import SemPermissao
from app.core.papeis import Papel, UsuarioAtual

LISTA = """
SELECT id_auditoria, criada_em AS data, autor_nome AS autor, acao, detalhe
FROM auditoria
WHERE (CAST(:busca AS text) IS NULL
       OR strpos(lower(autor_nome || ' ' || acao || ' ' || detalhe),
                 lower(CAST(:busca AS text))) > 0)
"""


def registrar(conexao: Connection, usuario: UsuarioAtual, acao: str, detalhe: str = "") -> None:
    """Grava na transacao aberta (quem chama faz o commit). Sem usuario ativo: `Sistema`."""
    pessoa = conexao.execute(
        text(
            "SELECT id_usuario, nome FROM usuario WHERE auth_user_id = CAST(:a AS uuid) AND ativo"
        ),
        {"a": str(usuario.id_auth)},
    ).first()
    conexao.execute(
        text(
            """
            INSERT INTO auditoria (id_usuario, autor_nome, acao, detalhe)
            VALUES (CAST(:id AS uuid), :autor, :acao, :detalhe)
            """
        ),
        {
            "id": str(pessoa[0]) if pessoa else None,
            "autor": pessoa[1] if pessoa else "Sistema",
            "acao": acao[:120],
            "detalhe": detalhe[:500],
        },
    )


def sku_da_variacao(conexao: Connection, id_variacao: UUID) -> str:
    return str(
        conexao.execute(
            text("SELECT sku FROM variacao_produto WHERE id_variacao = CAST(:v AS uuid)"),
            {"v": str(id_variacao)},
        ).scalar()
        or id_variacao
    )


def listar(
    conexao: Connection, usuario: UsuarioAtual, *, busca: str | None, limit: int, offset: int
) -> dict[str, Any]:
    if usuario.papel is not Papel.ADMIN:
        raise SemPermissao()
    parametros = {"busca": busca}
    total = conexao.execute(
        text("SELECT count(*) FROM (" + LISTA + ") t"),  # nosec B608
        parametros,
    ).scalar_one()
    linhas = conexao.execute(
        text(LISTA + " ORDER BY criada_em DESC, id_auditoria LIMIT :limite OFFSET :deslocamento"),  # nosec B608
        {**parametros, "limite": limit, "deslocamento": offset},
    ).mappings()
    return {"total": int(total), "itens": [dict(linha) for linha in linhas]}
