"""Consultas do saldo e do historico de movimentacoes, em SQLAlchemy (`text` com parametros).

Bandit B608: os textos SQL abaixo so juntam constantes deste modulo; todo valor vindo da requisicao
(busca, categoria, sku, datas...) entra por parametro nomeado, nunca por concatenacao. A conexao da
API ignora RLS, entao o escopo de loja (e o de "so as minhas") vem sempre do `Filtro...`, montado no
service a partir do token.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

FUSO = "America/Sao_Paulo"

SITUACOES = (("ok", "OK"), ("baixo", "Estoque baixo"), ("esgotado", "Esgotado"))
GRUPOS = (
    ("entrada", "Entrada"),
    ("saida", "Saída"),
    ("ajuste", "Ajuste"),
    ("transferencia", "Transferência"),
)

# Entrada, saida, ajuste ou transferencia. Tipo novo cadastrado depois cai em entrada ou saida
# pelo sinal, para nunca sumir do historico.
GRUPO_DO_TIPO = """
CASE
    WHEN t.codigo IN ('entrada', 'cancelamento_venda') THEN 'entrada'
    WHEN t.codigo IN ('saida', 'venda') THEN 'saida'
    WHEN t.codigo IN ('ajuste_positivo', 'ajuste_negativo') THEN 'ajuste'
    WHEN t.codigo IN ('transferencia_entrada', 'transferencia_saida') THEN 'transferencia'
    WHEN t.sinal > 0 THEN 'entrada'
    ELSE 'saida'
END
"""  # nosec B608


@dataclass(frozen=True)
class FiltroSaldo:
    id_loja: UUID | None = None
    busca: str | None = None
    categoria: str | None = None
    situacao: str | None = None

    def parametros(self) -> dict[str, Any]:
        return {
            "id_loja": str(self.id_loja) if self.id_loja else None,
            "busca": self.busca,
            "categoria": self.categoria,
            "situacao": self.situacao,
        }


@dataclass(frozen=True)
class FiltroMovimentacoes:
    id_loja: UUID | None = None
    grupo: str | None = None
    sku: str | None = None
    de: date | None = None
    ate: date | None = None
    # So o operador de estoque: apenas o que ele mesmo registrou.
    id_responsavel: UUID | None = None
    id_movimentacao: UUID | None = None

    def parametros(self) -> dict[str, Any]:
        return {
            "id_loja": str(self.id_loja) if self.id_loja else None,
            "grupo": self.grupo,
            "sku": self.sku,
            "de": self.de,
            "ate": self.ate,
            "id_responsavel": str(self.id_responsavel) if self.id_responsavel else None,
            "id_movimentacao": str(self.id_movimentacao) if self.id_movimentacao else None,
            "fuso": FUSO,
        }


# Uma linha por peca (variacao) que a loja (ou a rede) mantem em estoque, com o saldo somado.
SALDO_BASE = """
WITH saldo AS (
    SELECT
        v.id_variacao,
        v.sku,
        produto.nome AS produto,
        v.cor,
        v.tamanho,
        produto.categoria,
        v.preco_venda AS preco,
        sum(e.quantidade)::int AS total,
        sum(e.estoque_minimo)::int AS minimo_total,
        CASE
            WHEN sum(e.quantidade) = 0 THEN 'esgotado'
            WHEN sum(e.quantidade) <= sum(e.estoque_minimo) THEN 'baixo'
            ELSE 'ok'
        END AS situacao
    FROM estoque e
    JOIN variacao_produto v ON v.id_variacao = e.id_variacao AND v.ativa
    JOIN produto ON produto.id_produto = v.id_produto AND produto.ativo
    WHERE CAST(:id_loja AS uuid) IS NULL OR e.id_loja = CAST(:id_loja AS uuid)
    GROUP BY v.id_variacao, v.sku, produto.nome, v.cor, v.tamanho, produto.categoria,
             v.preco_venda
)
"""

# strpos em vez de LIKE: o texto digitado nunca vira curinga (%, _).
SALDO_FILTROS = """
WHERE (CAST(:busca AS text) IS NULL
       OR strpos(lower(produto || ' ' || sku), lower(CAST(:busca AS text))) > 0)
  AND (CAST(:categoria AS text) IS NULL OR categoria = CAST(:categoria AS text))
  AND (CAST(:situacao AS text) IS NULL OR situacao = CAST(:situacao AS text))
"""


_CATEGORIAS = "SELECT DISTINCT categoria FROM saldo WHERE categoria IS NOT NULL ORDER BY categoria"
_PECAS = (
    "SELECT id_variacao, sku, produto || ' · ' || cor || ', ' || tamanho AS nome "
    "FROM saldo ORDER BY produto, cor, tamanho"
)
_ITENS = "ORDER BY produto, cor, tamanho, sku LIMIT :limite OFFSET :deslocamento"
CATEGORIAS_SQL = SALDO_BASE + _CATEGORIAS  # nosec B608
PECAS_SQL = SALDO_BASE + _PECAS  # nosec B608
ITENS_SQL = SALDO_BASE + "SELECT * FROM saldo " + SALDO_FILTROS + _ITENS  # nosec B608
CONTAGEM_SQL = SALDO_BASE + "SELECT count(*) FROM saldo " + SALDO_FILTROS  # nosec B608


def lojas_visiveis(conexao: Connection, id_loja: UUID | None) -> list[dict[str, Any]]:
    linhas = conexao.execute(
        text(
            """
            SELECT id_loja, nome FROM loja
            WHERE ativa AND (CAST(:id_loja AS uuid) IS NULL OR id_loja = CAST(:id_loja AS uuid))
            ORDER BY nome
            """
        ),
        {"id_loja": str(id_loja) if id_loja else None},
    ).mappings()
    return [dict(linha) for linha in linhas]


def loja_por_id(conexao: Connection, id_loja: UUID) -> dict[str, Any] | None:
    linha = (
        conexao.execute(
            text("SELECT id_loja, nome FROM loja WHERE id_loja = :id_loja"),
            {"id_loja": str(id_loja)},
        )
        .mappings()
        .first()
    )
    return dict(linha) if linha else None


def categorias(conexao: Connection, id_loja: UUID | None) -> list[str]:
    return list(
        conexao.execute(
            text(CATEGORIAS_SQL), {"id_loja": str(id_loja) if id_loja else None}
        ).scalars()
    )


def pecas(conexao: Connection, id_loja: UUID | None) -> list[dict[str, Any]]:
    linhas = conexao.execute(
        text(PECAS_SQL), {"id_loja": str(id_loja) if id_loja else None}
    ).mappings()
    return [dict(linha) for linha in linhas]


def resumo_do_saldo(conexao: Connection, id_loja: UUID | None) -> dict[str, Any]:
    """Totais da loja (ou da rede), sem os filtros da tela."""
    linha = (
        conexao.execute(
            text(
                SALDO_BASE
                + """
                SELECT
                    COALESCE(sum(total), 0) AS unidades,
                    count(*) AS pecas,
                    count(*) FILTER (WHERE situacao = 'baixo') AS estoque_baixo,
                    count(*) FILTER (WHERE situacao = 'esgotado') AS esgotadas,
                    COALESCE(sum(total * preco), 0) AS valor_em_estoque
                FROM saldo
                """  # nosec B608
            ),
            {"id_loja": str(id_loja) if id_loja else None},
        )
        .mappings()
        .one()
    )
    return dict(linha)


def itens_do_saldo(
    conexao: Connection, filtro: FiltroSaldo, *, limit: int, offset: int
) -> tuple[int, list[dict[str, Any]]]:
    parametros = filtro.parametros()
    total = conexao.execute(text(CONTAGEM_SQL), parametros).scalar_one()
    linhas = conexao.execute(
        text(ITENS_SQL), {**parametros, "limite": limit, "deslocamento": offset}
    ).mappings()
    return int(total), [dict(linha) for linha in linhas]


def saldo_por_loja(
    conexao: Connection, ids_variacao: list[UUID], id_loja: UUID | None
) -> dict[UUID, list[dict[str, Any]]]:
    """Saldo e minimo de cada peca em cada loja visivel (as colunas por unidade da tabela)."""
    if not ids_variacao:
        return {}
    linhas = conexao.execute(
        text(
            """
            SELECT e.id_variacao, e.id_loja, e.quantidade, e.estoque_minimo AS minimo
            FROM estoque e
            JOIN loja l ON l.id_loja = e.id_loja AND l.ativa
            WHERE e.id_variacao = ANY(CAST(:ids AS uuid[]))
              AND (CAST(:id_loja AS uuid) IS NULL OR e.id_loja = CAST(:id_loja AS uuid))
            ORDER BY l.nome
            """
        ),
        {"ids": [str(i) for i in ids_variacao], "id_loja": str(id_loja) if id_loja else None},
    ).mappings()
    agrupado: dict[UUID, list[dict[str, Any]]] = {}
    for linha in linhas:
        agrupado.setdefault(linha["id_variacao"], []).append(
            {
                "id_loja": linha["id_loja"],
                "quantidade": linha["quantidade"],
                "minimo": linha["minimo"],
            }
        )
    return agrupado


MOVIMENTACOES_DE = f"""
FROM movimentacao_estoque m
JOIN tipo_movimentacao_estoque t
    ON t.id_tipo_movimentacao_estoque = m.id_tipo_movimentacao_estoque
JOIN loja ON loja.id_loja = m.id_loja
JOIN variacao_produto v ON v.id_variacao = m.id_variacao
JOIN produto ON produto.id_produto = v.id_produto
LEFT JOIN usuario responsavel ON responsavel.id_usuario = m.id_usuario_responsavel
LEFT JOIN pedido ON pedido.id_pedido = m.id_pedido
WHERE (CAST(:id_loja AS uuid) IS NULL OR m.id_loja = CAST(:id_loja AS uuid))
  AND (CAST(:grupo AS text) IS NULL OR ({GRUPO_DO_TIPO}) = CAST(:grupo AS text))
  AND (CAST(:sku AS text) IS NULL OR v.sku = CAST(:sku AS text))
  AND (CAST(:de AS date) IS NULL
       OR m.criada_em >= CAST(:de AS date)::timestamp AT TIME ZONE :fuso)
  AND (CAST(:ate AS date) IS NULL
       OR m.criada_em < (CAST(:ate AS date) + 1)::timestamp AT TIME ZONE :fuso)
  AND (CAST(:id_responsavel AS uuid) IS NULL
       OR m.id_usuario_responsavel = CAST(:id_responsavel AS uuid))
  AND (CAST(:id_movimentacao AS uuid) IS NULL
       OR m.id_movimentacao_estoque = CAST(:id_movimentacao AS uuid))
"""  # nosec B608


def movimentacoes(
    conexao: Connection, filtro: FiltroMovimentacoes, *, limit: int, offset: int
) -> tuple[int, list[dict[str, Any]]]:
    parametros = filtro.parametros()
    total = conexao.execute(
        text("SELECT count(*) " + MOVIMENTACOES_DE),
        parametros,  # nosec B608
    ).scalar_one()
    linhas = conexao.execute(
        text(
            f"""
            SELECT
                m.id_movimentacao_estoque AS id_movimentacao,
                m.criada_em AS data,
                m.id_loja,
                loja.nome AS loja_nome,
                v.id_variacao,
                v.sku,
                produto.nome AS produto,
                v.cor,
                v.tamanho,
                t.codigo AS tipo_codigo,
                t.nome AS tipo_nome,
                {GRUPO_DO_TIPO} AS grupo,
                (m.quantidade * t.sinal)::int AS quantidade,
                m.quantidade_anterior,
                m.quantidade_posterior,
                responsavel.nome AS responsavel,
                m.motivo,
                pedido.numero_pedido
            """  # nosec B608
            + MOVIMENTACOES_DE
            + "ORDER BY m.criada_em DESC, m.id_movimentacao_estoque DESC "
            "LIMIT :limite OFFSET :deslocamento"
        ),
        {**parametros, "limite": limit, "deslocamento": offset},
    ).mappings()
    return int(total), [dict(linha) for linha in linhas]
