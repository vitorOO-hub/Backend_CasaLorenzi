"""Catalogo do admin: pecas (produto + variacoes) e preco, com estoque somado da rede.

A conexao da API ignora RLS: quem chama e decidido no router (so admin). Cada acao grava na
auditoria na mesma transacao.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from app.core.erros_auth import SemPermissao
from app.core.papeis import Papel, UsuarioAtual
from app.gestao import auditoria
from app.gestao.erros import NomeDePecaJaExiste, PecaEmUso, PecaNaoEncontrada, SkuJaExiste
from app.gestao.schemas import NovaPeca, PecaAlterada

MARCA = "Casa Lorenzi"

# Uma linha por peca ativa: o menor preco de venda, os SKUs e o estoque somado de todas as lojas.
PECAS = """
SELECT * FROM (
    SELECT
        p.id_produto,
        p.nome,
        p.categoria,
        COALESCE(min(v.preco_venda) FILTER (WHERE v.ativa), p.preco_base) AS preco,
        COALESCE(array_agg(DISTINCT v.sku ORDER BY v.sku) FILTER (WHERE v.ativa), '{}') AS skus,
        count(DISTINCT v.id_variacao) FILTER (WHERE v.ativa) AS variacoes,
        COALESCE(sum(e.quantidade) FILTER (WHERE v.ativa), 0) AS estoque_rede
    FROM produto p
    LEFT JOIN variacao_produto v ON v.id_produto = p.id_produto
    LEFT JOIN estoque e ON e.id_variacao = v.id_variacao
    WHERE p.ativo
    GROUP BY p.id_produto, p.nome, p.categoria, p.preco_base
) peca
"""

# strpos em vez de LIKE: o texto digitado nunca vira curinga (%, _).
FILTRO = """
WHERE (CAST(:busca AS text) IS NULL
       OR strpos(lower(nome || ' ' || array_to_string(skus, ' ') || ' ' || COALESCE(categoria, '')),
                 lower(CAST(:busca AS text))) > 0)
"""


# Textos fixos: so o id da peca entra, por parametro nomeado.
APAGAR_DO_CARRINHO = (
    "DELETE FROM carrinho WHERE id_variacao IN "
    "(SELECT id_variacao FROM variacao_produto WHERE id_produto = CAST(:id AS uuid))"
)
APAGAR_DO_ESTOQUE = (
    "DELETE FROM estoque WHERE id_variacao IN "
    "(SELECT id_variacao FROM variacao_produto WHERE id_produto = CAST(:id AS uuid))"
)


def _so_admin(usuario: UsuarioAtual) -> None:
    if usuario.papel is not Papel.ADMIN:
        raise SemPermissao()


def _peca(linha: dict[str, Any]) -> dict[str, Any]:
    return {
        **linha,
        "preco": round(float(linha["preco"]), 2),
        "skus": list(linha["skus"]),
        "variacoes": int(linha["variacoes"]),
        "estoque_rede": int(linha["estoque_rede"]),
    }


def _uma(conexao: Connection, id_produto: UUID) -> dict[str, Any] | None:
    linha = (
        conexao.execute(
            text(PECAS + " WHERE id_produto = CAST(:id AS uuid)"), {"id": str(id_produto)}
        )
        .mappings()
        .first()
    )
    return _peca(dict(linha)) if linha else None


def listar(
    conexao: Connection, usuario: UsuarioAtual, *, busca: str | None, limit: int, offset: int
) -> dict[str, Any]:
    _so_admin(usuario)
    total = conexao.execute(
        text("SELECT count(*) FROM (" + PECAS + FILTRO + ") t"),  # nosec B608
        {"busca": busca},
    ).scalar_one()
    linhas = conexao.execute(
        text(PECAS + FILTRO + " ORDER BY nome, id_produto LIMIT :limite OFFSET :deslocamento"),  # nosec B608
        {"busca": busca, "limite": limit, "deslocamento": offset},
    ).mappings()
    return {"total": int(total), "itens": [_peca(dict(linha)) for linha in linhas]}


def criar(conexao: Connection, usuario: UsuarioAtual, dados: NovaPeca) -> dict[str, Any]:
    """Peca nova = produto + a primeira variacao (cor e tamanho unicos) com o SKU informado."""
    _so_admin(usuario)
    try:
        if conexao.execute(
            text("SELECT 1 FROM variacao_produto WHERE lower(sku) = lower(:sku)"),
            {"sku": dados.sku},
        ).scalar():
            raise SkuJaExiste()
        if conexao.execute(
            text("SELECT 1 FROM produto WHERE lower(nome) = lower(:nome) AND marca = :marca"),
            {"nome": dados.nome, "marca": MARCA},
        ).scalar():
            raise NomeDePecaJaExiste()
        id_produto = conexao.execute(
            text(
                """
                INSERT INTO produto (nome, marca, categoria, preco_base)
                VALUES (:nome, :marca, :categoria, :preco) RETURNING id_produto
                """
            ),
            {
                "nome": dados.nome,
                "marca": MARCA,
                "categoria": dados.categoria,
                "preco": dados.preco,
            },
        ).scalar_one()
        conexao.execute(
            text(
                """
                INSERT INTO variacao_produto (id_produto, sku, cor, tamanho, preco_venda)
                VALUES (:produto, :sku, 'Única', 'Único', :preco)
                """
            ),
            {"produto": id_produto, "sku": dados.sku, "preco": dados.preco},
        )
        auditoria.registrar(
            conexao, usuario, "Criou produto no catálogo", f"{dados.sku} · {dados.nome}"
        )
        conexao.commit()
    except IntegrityError as erro:
        conexao.rollback()
        raise SkuJaExiste() from erro
    except Exception:
        conexao.rollback()
        raise
    return _uma(conexao, id_produto) or {}


def alterar(
    conexao: Connection, usuario: UsuarioAtual, id_produto: UUID, dados: PecaAlterada
) -> dict[str, Any]:
    """Nome e categoria da peca; o preco vale para todas as variacoes (e para o preco base)."""
    _so_admin(usuario)
    try:
        atual = conexao.execute(
            text(
                "SELECT nome FROM produto WHERE id_produto = CAST(:id AS uuid) AND ativo FOR UPDATE"
            ),
            {"id": str(id_produto)},
        ).first()
        if atual is None:
            raise PecaNaoEncontrada()
        if (
            dados.nome is not None
            and conexao.execute(
                text(
                    "SELECT 1 FROM produto WHERE lower(nome) = lower(:nome) AND marca = :marca "
                    "AND id_produto <> CAST(:id AS uuid)"
                ),
                {"nome": dados.nome, "marca": MARCA, "id": str(id_produto)},
            ).scalar()
        ):
            raise NomeDePecaJaExiste()
        conexao.execute(
            text(
                """
                UPDATE produto
                SET nome = COALESCE(:nome, nome),
                    categoria = COALESCE(:categoria, categoria),
                    preco_base = COALESCE(:preco, preco_base),
                    atualizado_em = now()
                WHERE id_produto = CAST(:id AS uuid)
                """
            ),
            {
                "nome": dados.nome,
                "categoria": dados.categoria,
                "preco": dados.preco,
                "id": str(id_produto),
            },
        )
        if dados.preco is not None:
            conexao.execute(
                text(
                    "UPDATE variacao_produto SET preco_venda = :preco, atualizada_em = now() "
                    "WHERE id_produto = CAST(:id AS uuid)"
                ),
                {"preco": dados.preco, "id": str(id_produto)},
            )
        sku = conexao.execute(
            text("SELECT min(sku) FROM variacao_produto WHERE id_produto = CAST(:id AS uuid)"),
            {"id": str(id_produto)},
        ).scalar()
        auditoria.registrar(
            conexao,
            usuario,
            "Editou produto do catálogo",
            f"{sku or '?'} · {dados.nome or atual[0]}",
        )
        conexao.commit()
    except IntegrityError as erro:
        conexao.rollback()
        raise NomeDePecaJaExiste() from erro
    except Exception:
        conexao.rollback()
        raise
    return _uma(conexao, id_produto) or {}


def excluir(conexao: Connection, usuario: UsuarioAtual, id_produto: UUID) -> dict[str, Any]:
    """Tira a peca do catalogo. Peca com estoque, pedido ou historico de estoque nao sai."""
    _so_admin(usuario)
    try:
        peca = conexao.execute(
            text("SELECT nome FROM produto WHERE id_produto = CAST(:id AS uuid) FOR UPDATE"),
            {"id": str(id_produto)},
        ).first()
        if peca is None:
            raise PecaNaoEncontrada()
        usos = conexao.execute(
            text(
                """
                SELECT
                    COALESCE((SELECT sum(e.quantidade) FROM estoque e
                              JOIN variacao_produto v ON v.id_variacao = e.id_variacao
                              WHERE v.id_produto = CAST(:id AS uuid)), 0) AS estoque,
                    (SELECT count(*) FROM item_pedido i
                     JOIN variacao_produto v ON v.id_variacao = i.id_variacao
                     WHERE v.id_produto = CAST(:id AS uuid)) AS pedidos,
                    (SELECT count(*) FROM movimentacao_estoque m
                     JOIN variacao_produto v ON v.id_variacao = m.id_variacao
                     WHERE v.id_produto = CAST(:id AS uuid)) AS movimentos
                """
            ),
            {"id": str(id_produto)},
        ).one()
        if usos.estoque or usos.pedidos or usos.movimentos:
            raise PecaEmUso()
        skus = [
            linha[0]
            for linha in conexao.execute(
                text("SELECT sku FROM variacao_produto WHERE id_produto = CAST(:id AS uuid)"),
                {"id": str(id_produto)},
            )
        ]
        for apagar in (APAGAR_DO_CARRINHO, APAGAR_DO_ESTOQUE):
            conexao.execute(text(apagar), {"id": str(id_produto)})
        conexao.execute(
            text("DELETE FROM variacao_produto WHERE id_produto = CAST(:id AS uuid)"),
            {"id": str(id_produto)},
        )
        conexao.execute(
            text("DELETE FROM produto WHERE id_produto = CAST(:id AS uuid)"),
            {"id": str(id_produto)},
        )
        auditoria.registrar(
            conexao, usuario, "Excluiu produto do catálogo", f"{', '.join(skus) or '?'} · {peca[0]}"
        )
        conexao.commit()
    except IntegrityError as erro:
        # Alguma outra tabela ainda aponta para a peca (agendamento, ajuste, transferencia...).
        conexao.rollback()
        raise PecaEmUso() from erro
    except Exception:
        conexao.rollback()
        raise
    return {"id_produto": id_produto, "excluido": True}
