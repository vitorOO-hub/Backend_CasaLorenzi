"""Escrita do estoque do painel: movimentacoes e ajustes de inventario, em SQLAlchemy Core.

Bandit B608: os textos SQL juntam so constantes deste modulo; todo valor vindo da requisicao entra
por parametro nomeado. Toda gravacao acontece na transacao do chamador (o service faz o commit), e
o saldo so muda depois de a linha do estoque ser travada.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection


def achar_peca(conexao: Connection, sku: str) -> UUID | None:
    """Id da variacao ativa (de produto ativo) com esse SKU."""
    return conexao.execute(
        text(
            """
            SELECT v.id_variacao FROM variacao_produto v
            JOIN produto ON produto.id_produto = v.id_produto
            WHERE v.sku = :sku AND v.ativa AND produto.ativo
            """
        ),
        {"sku": sku},
    ).scalar()


def travar_estoque(conexao: Connection, id_loja: UUID, id_variacao: UUID) -> int | None:
    """Trava a linha do estoque ate o fim da transacao e devolve o saldo (None se nao existe).

    Sem junções de proposito: duas saidas ao mesmo tempo se enfileiram aqui, e a segunda le o saldo
    que a primeira confirmou, em vez de decidir com um valor velho.
    """
    return conexao.execute(
        text(
            """
            SELECT quantidade FROM estoque
            WHERE id_loja = CAST(:id_loja AS uuid) AND id_variacao = CAST(:id_variacao AS uuid)
            FOR UPDATE
            """
        ),
        {"id_loja": str(id_loja), "id_variacao": str(id_variacao)},
    ).scalar()


def criar_linha_de_estoque(conexao: Connection, id_loja: UUID, id_variacao: UUID) -> None:
    """Primeira entrada de uma peca na loja: nasce zerada, com minimo 0 (a gestao ajusta depois)."""
    conexao.execute(
        text(
            """
            INSERT INTO estoque (id_loja, id_variacao, quantidade, estoque_minimo)
            VALUES (CAST(:id_loja AS uuid), CAST(:id_variacao AS uuid), 0, 0)
            ON CONFLICT (id_loja, id_variacao) DO NOTHING
            """
        ),
        {"id_loja": str(id_loja), "id_variacao": str(id_variacao)},
    )


def gravar_movimentacao(
    conexao: Connection,
    *,
    id_loja: UUID,
    id_variacao: UUID,
    id_usuario: UUID,
    tipo: str,
    quantidade: int,
    anterior: int,
    posterior: int,
    motivo: str,
) -> UUID:
    """Lanca a movimentacao e leva o saldo da loja ao novo valor (o banco confere o sinal)."""
    id_movimentacao = conexao.execute(
        text(
            """
            INSERT INTO movimentacao_estoque (
                id_loja, id_variacao, id_usuario_responsavel, id_tipo_movimentacao_estoque,
                quantidade, quantidade_anterior, quantidade_posterior, motivo)
            VALUES (
                CAST(:id_loja AS uuid), CAST(:id_variacao AS uuid), CAST(:id_usuario AS uuid),
                (SELECT id_tipo_movimentacao_estoque FROM tipo_movimentacao_estoque
                 WHERE codigo = :tipo),
                :quantidade, :anterior, :posterior, :motivo)
            RETURNING id_movimentacao_estoque
            """
        ),
        {
            "id_loja": str(id_loja),
            "id_variacao": str(id_variacao),
            "id_usuario": str(id_usuario),
            "tipo": tipo,
            "quantidade": quantidade,
            "anterior": anterior,
            "posterior": posterior,
            "motivo": motivo,
        },
    ).scalar_one()
    conexao.execute(
        text(
            """
            UPDATE estoque SET quantidade = :posterior, atualizado_em = now()
            WHERE id_loja = CAST(:id_loja AS uuid) AND id_variacao = CAST(:id_variacao AS uuid)
            """
        ),
        {"posterior": posterior, "id_loja": str(id_loja), "id_variacao": str(id_variacao)},
    )
    return id_movimentacao


def criar_ajuste(
    conexao: Connection,
    *,
    id_loja: UUID,
    id_variacao: UUID,
    id_solicitante: UUID,
    quantidade: int,
    motivo: str,
) -> UUID:
    return conexao.execute(
        text(
            """
            INSERT INTO ajuste_estoque (
                id_loja, id_variacao, id_usuario_solicitante, quantidade, motivo)
            VALUES (CAST(:id_loja AS uuid), CAST(:id_variacao AS uuid),
                    CAST(:id_solicitante AS uuid), :quantidade, :motivo)
            RETURNING id_ajuste_estoque
            """
        ),
        {
            "id_loja": str(id_loja),
            "id_variacao": str(id_variacao),
            "id_solicitante": str(id_solicitante),
            "quantidade": quantidade,
            "motivo": motivo,
        },
    ).scalar_one()


def travar_ajuste(
    conexao: Connection, id_ajuste: UUID, id_loja: UUID | None
) -> dict[str, Any] | None:
    """Trava o ajuste (so se estiver no escopo de loja) e le o estado confirmado.

    Sem junções na trava, pelo mesmo motivo do estoque: quem perde a corrida enxerga que o ajuste
    ja foi decidido (409) em vez de "nao encontrado".
    """
    travado = conexao.execute(
        text(
            """
            SELECT id_ajuste_estoque FROM ajuste_estoque
            WHERE id_ajuste_estoque = CAST(:id AS uuid)
              AND (CAST(:id_loja AS uuid) IS NULL OR id_loja = CAST(:id_loja AS uuid))
            FOR UPDATE
            """
        ),
        {"id": str(id_ajuste), "id_loja": str(id_loja) if id_loja else None},
    ).first()
    if travado is None:
        return None
    linha = (
        conexao.execute(
            text(
                """
                SELECT id_loja, id_variacao, id_usuario_solicitante, quantidade, motivo, status
                FROM ajuste_estoque WHERE id_ajuste_estoque = CAST(:id AS uuid)
                """
            ),
            {"id": str(id_ajuste)},
        )
        .mappings()
        .one()
    )
    return dict(linha)


def decidir_ajuste(
    conexao: Connection,
    id_ajuste: UUID,
    *,
    status: str,
    id_decisor: UUID,
    motivo_recusa: str | None,
) -> None:
    conexao.execute(
        text(
            """
            UPDATE ajuste_estoque
            SET status = :status, id_usuario_decisor = CAST(:decisor AS uuid),
                decidido_em = now(), motivo_recusa = :motivo_recusa
            WHERE id_ajuste_estoque = CAST(:id AS uuid)
            """
        ),
        {
            "status": status,
            "decisor": str(id_decisor),
            "motivo_recusa": motivo_recusa,
            "id": str(id_ajuste),
        },
    )


AJUSTES_DE = """
FROM ajuste_estoque a
JOIN loja ON loja.id_loja = a.id_loja
JOIN variacao_produto v ON v.id_variacao = a.id_variacao
JOIN produto ON produto.id_produto = v.id_produto
JOIN usuario solicitante ON solicitante.id_usuario = a.id_usuario_solicitante
LEFT JOIN usuario decisor ON decisor.id_usuario = a.id_usuario_decisor
LEFT JOIN estoque e ON e.id_loja = a.id_loja AND e.id_variacao = a.id_variacao
WHERE (CAST(:id_loja AS uuid) IS NULL OR a.id_loja = CAST(:id_loja AS uuid))
  AND (CAST(:id_solicitante AS uuid) IS NULL
       OR a.id_usuario_solicitante = CAST(:id_solicitante AS uuid))
  AND (CAST(:id_ajuste AS uuid) IS NULL OR a.id_ajuste_estoque = CAST(:id_ajuste AS uuid))
  AND (
      CAST(:status AS text) IS NULL
      OR a.status = CAST(:status AS text)
      OR (CAST(:status AS text) = 'decididos' AND a.status <> 'pendente')
  )
"""

AJUSTES_SELECT = """
SELECT
    a.id_ajuste_estoque AS id_ajuste,
    a.id_loja,
    loja.nome AS loja_nome,
    v.id_variacao,
    v.sku,
    produto.nome AS produto,
    v.cor,
    v.tamanho,
    a.quantidade,
    COALESCE(e.quantidade, 0)::int AS saldo_atual,
    a.motivo,
    a.status,
    a.motivo_recusa,
    solicitante.nome AS solicitante,
    decisor.nome AS decisor,
    a.solicitado_em,
    a.decidido_em
"""
ORDEM_DOS_AJUSTES = (
    " ORDER BY COALESCE(a.decidido_em, a.solicitado_em) DESC, a.id_ajuste_estoque DESC"
)
PAGINA = " LIMIT :limite OFFSET :deslocamento"
CONTAGEM_DE_AJUSTES = "SELECT count(*) " + AJUSTES_DE  # nosec B608
LISTA_DE_AJUSTES = AJUSTES_SELECT + AJUSTES_DE + ORDEM_DOS_AJUSTES + PAGINA  # nosec B608


def ajustes(
    conexao: Connection,
    *,
    id_loja: UUID | None,
    id_solicitante: UUID | None,
    status: str | None,
    id_ajuste: UUID | None = None,
    limit: int,
    offset: int,
) -> tuple[int, int, list[dict[str, Any]]]:
    """(total do filtro, pendentes no escopo, itens da pagina)."""
    parametros = {
        "id_loja": str(id_loja) if id_loja else None,
        "id_solicitante": str(id_solicitante) if id_solicitante else None,
        "status": status,
        "id_ajuste": str(id_ajuste) if id_ajuste else None,
    }
    total = conexao.execute(text(CONTAGEM_DE_AJUSTES), parametros).scalar_one()
    pendentes = conexao.execute(
        text(CONTAGEM_DE_AJUSTES), {**parametros, "status": "pendente", "id_ajuste": None}
    ).scalar_one()
    linhas = conexao.execute(
        text(LISTA_DE_AJUSTES), {**parametros, "limite": limit, "deslocamento": offset}
    ).mappings()
    return int(total), int(pendentes), [dict(linha) for linha in linhas]
