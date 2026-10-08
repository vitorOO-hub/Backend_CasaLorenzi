"""Integracao com o ERP (Vulto): lotes recebidos e registros que ainda precisam de um SKU.

A conexao da API ignora RLS: quem chama e decidido no router (so admin).
"""

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.erros_auth import SemPermissao
from app.core.papeis import Papel, UsuarioAtual
from app.gestao import auditoria
from app.gestao.erros import RegistroJaMapeado, RegistroNaoEncontrado, SkuInvalido

LIMITE_LOTES = 20
LIMITE_REGISTROS = 100

LOTES = """
SELECT l.codigo, l.origem, l.recebido_em, l.com_erro,
       count(r.id_registro) AS registros,
       count(r.id_registro) FILTER (WHERE r.id_variacao IS NULL) AS pendentes
FROM importacao_lote l
LEFT JOIN importacao_registro r ON r.id_lote = l.id_lote
GROUP BY l.id_lote, l.codigo, l.origem, l.recebido_em, l.com_erro
ORDER BY l.recebido_em DESC, l.codigo DESC
LIMIT :limite
"""

# Os que esperam um SKU primeiro; depois os ja mapeados, do lote mais novo para o mais antigo.
REGISTROS = """
SELECT r.id_registro, l.codigo AS lote, r.descricao_externa, r.codigo_externo, v.sku AS sku_mapeado
FROM importacao_registro r
JOIN importacao_lote l ON l.id_lote = r.id_lote
LEFT JOIN variacao_produto v ON v.id_variacao = r.id_variacao
ORDER BY (r.id_variacao IS NULL) DESC, l.recebido_em DESC, r.descricao_externa, r.codigo_externo
LIMIT :limite
"""

SKUS = """
SELECT v.id_variacao, v.sku, p.nome || ' · ' || v.cor || ', ' || v.tamanho AS nome
FROM variacao_produto v
JOIN produto p ON p.id_produto = v.id_produto
WHERE v.ativa AND p.ativo
ORDER BY p.nome, v.cor, v.tamanho
"""

UM_REGISTRO = """
SELECT r.id_registro, l.codigo AS lote, r.descricao_externa, r.codigo_externo, v.sku AS sku_mapeado
FROM importacao_registro r
JOIN importacao_lote l ON l.id_lote = r.id_lote
LEFT JOIN variacao_produto v ON v.id_variacao = r.id_variacao
WHERE r.id_registro = CAST(:id AS uuid)
"""


def _so_admin(usuario: UsuarioAtual) -> None:
    if usuario.papel is not Papel.ADMIN:
        raise SemPermissao()


def _situacao(linha: dict[str, Any]) -> str:
    if linha["com_erro"]:
        return "com_erro"
    return "pendente_mapeamento" if linha["pendentes"] else "processado"


def montar(conexao: Connection, usuario: UsuarioAtual) -> dict[str, Any]:
    _so_admin(usuario)
    lotes = conexao.execute(text(LOTES), {"limite": LIMITE_LOTES}).mappings()
    registros = conexao.execute(text(REGISTROS), {"limite": LIMITE_REGISTROS}).mappings()
    skus = conexao.execute(text(SKUS)).mappings()
    return {
        "lotes": [
            {
                "codigo": lote["codigo"],
                "origem": lote["origem"],
                "recebido_em": lote["recebido_em"],
                "registros": int(lote["registros"]),
                "pendentes": int(lote["pendentes"]),
                "situacao": _situacao(dict(lote)),
            }
            for lote in lotes
        ],
        "registros": [dict(registro) for registro in registros],
        "skus": [dict(sku) for sku in skus],
    }


def mapear(
    conexao: Connection, usuario: UsuarioAtual, id_registro: UUID, id_variacao: UUID
) -> dict[str, Any]:
    """Liga o codigo do ERP a um SKU. O mesmo codigo, em outros lotes, ganha o mesmo SKU."""
    _so_admin(usuario)
    try:
        registro = conexao.execute(
            text(
                "SELECT codigo_externo, id_variacao FROM importacao_registro "
                "WHERE id_registro = CAST(:id AS uuid) FOR UPDATE"
            ),
            {"id": str(id_registro)},
        ).first()
        if registro is None:
            raise RegistroNaoEncontrado()
        if registro[1] is not None:
            raise RegistroJaMapeado()
        sku = conexao.execute(
            text(
                """
                SELECT v.sku FROM variacao_produto v
                JOIN produto p ON p.id_produto = v.id_produto
                WHERE v.id_variacao = CAST(:v AS uuid) AND v.ativa AND p.ativo
                """
            ),
            {"v": str(id_variacao)},
        ).scalar()
        if sku is None:
            raise SkuInvalido()
        pessoa = conexao.execute(
            text("SELECT id_usuario FROM usuario WHERE auth_user_id = CAST(:a AS uuid) AND ativo"),
            {"a": str(usuario.id_auth)},
        ).scalar()
        conexao.execute(
            text(
                """
                UPDATE importacao_registro
                SET id_variacao = CAST(:v AS uuid), mapeado_em = now(),
                    id_usuario_mapeou = CAST(:u AS uuid)
                WHERE codigo_externo = :codigo AND id_variacao IS NULL
                """
            ),
            {
                "v": str(id_variacao),
                "u": str(pessoa) if pessoa else None,
                "codigo": registro[0],
            },
        )
        auditoria.registrar(
            conexao, usuario, "Mapeou registro de importação", f"{registro[0]} → {sku}"
        )
        conexao.commit()
    except Exception:
        conexao.rollback()
        raise
    linha = conexao.execute(text(UM_REGISTRO), {"id": str(id_registro)}).mappings().one()
    return dict(linha)
