"""Consultas do inicio do gerente, em SQLAlchemy (`text` com parametros ligados).

Bandit B608: os textos SQL abaixo so juntam constantes deste modulo; todo valor vindo da requisicao
entra por parametro nomeado (:inicio, :id_loja, ...), nunca por concatenacao. A conexao da API
ignora RLS, entao o escopo de loja vem sempre do `Filtro`, montado no service a partir do token.

Venda = pedido pago, separado ou entregue. Pedido criado, aguardando pagamento ou cancelado nao
conta. O faturamento soma os itens (sem frete), por isso o filtro de categoria e o total batem.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

FUSO = "America/Sao_Paulo"
STATUS_DE_VENDA = ("pago", "separado", "entregue")
CANAIS_DE_VENDA = (("loja", "Loja"), ("online", "Online"))
DIAS_DE_GIRO = 30
COBERTURA_CURTA_EM_DIAS = 21


@dataclass(frozen=True)
class Filtro:
    id_loja: UUID | None = None
    categoria: str | None = None
    canal: str | None = None
    # Varias lojas ao mesmo tempo (comparacao do admin). Vazio = nao restringe por esta lista.
    ids_loja: tuple[UUID, ...] = ()

    def parametros(self) -> dict[str, Any]:
        return {
            "id_loja": str(self.id_loja) if self.id_loja else None,
            "ids_loja": [str(i) for i in self.ids_loja],
            "categoria": self.categoria,
            "canal": self.canal,
            "status_de_venda": list(STATUS_DE_VENDA),
            "fuso": FUSO,
        }


# Uma linha por item vendido no periodo, ja no fuso de Sao Paulo (o "dia" bate com o do front).
VENDAS = """
WITH venda AS (
    SELECT
        p.id_pedido,
        p.id_loja,
        p.canal_venda,
        (p.criado_em AT TIME ZONE :fuso)::date AS dia,
        i.quantidade,
        i.valor_total AS valor,
        produto.id_produto,
        produto.nome AS produto,
        produto.categoria
    FROM pedido p
    JOIN status_pedido s ON s.id_status_pedido = p.id_status_pedido
    JOIN item_pedido i ON i.id_pedido = p.id_pedido
    JOIN variacao_produto v ON v.id_variacao = i.id_variacao
    JOIN produto ON produto.id_produto = v.id_produto
    WHERE s.codigo = ANY(CAST(:status_de_venda AS text[]))
      AND p.criado_em >= CAST(:inicio AS date)::timestamp AT TIME ZONE :fuso
      AND p.criado_em < (CAST(:fim AS date) + 1)::timestamp AT TIME ZONE :fuso
      AND (CAST(:id_loja AS uuid) IS NULL OR p.id_loja = CAST(:id_loja AS uuid))
      AND (cardinality(CAST(:ids_loja AS uuid[])) = 0
           OR p.id_loja = ANY(CAST(:ids_loja AS uuid[])))
      AND (CAST(:canal AS text) IS NULL OR p.canal_venda = CAST(:canal AS text))
      AND (CAST(:categoria AS text) IS NULL OR produto.categoria = CAST(:categoria AS text))
)
"""


def _parametros(filtro: Filtro, inicio: date, fim: date) -> dict[str, Any]:
    return {**filtro.parametros(), "inicio": inicio, "fim": fim}


def resumo(conexao: Connection, filtro: Filtro, inicio: date, fim: date) -> dict[str, Any]:
    linha = (
        conexao.execute(
            text(
                VENDAS
                + """
                SELECT
                    COALESCE(sum(valor), 0) AS faturamento,
                    count(DISTINCT id_pedido) AS pedidos,
                    COALESCE(sum(quantidade), 0) AS pecas,
                    COALESCE(sum(valor) FILTER (WHERE canal_venda = 'online'), 0)
                        AS faturamento_online,
                    count(DISTINCT id_pedido) FILTER (WHERE canal_venda = 'online')
                        AS pedidos_online
                FROM venda
                """  # nosec B608
            ),
            _parametros(filtro, inicio, fim),
        )
        .mappings()
        .one()
    )
    return dict(linha)


def serie_diaria(
    conexao: Connection, filtro: Filtro, inicio: date, fim: date
) -> list[dict[str, Any]]:
    linhas = conexao.execute(
        text(
            VENDAS
            + """
            SELECT
                dias.dia::date AS data,
                COALESCE(sum(venda.valor), 0) AS faturamento,
                count(DISTINCT venda.id_pedido) AS pedidos,
                COALESCE(sum(venda.quantidade), 0) AS pecas
            FROM generate_series(
                CAST(:inicio AS date), CAST(:fim AS date), interval '1 day'
            ) AS dias(dia)
            LEFT JOIN venda ON venda.dia = dias.dia::date
            GROUP BY dias.dia
            ORDER BY dias.dia
            """  # nosec B608
        ),
        _parametros(filtro, inicio, fim),
    ).mappings()
    return [dict(linha) for linha in linhas]


def movimento_semana(
    conexao: Connection, filtro: Filtro, inicio: date, fim: date
) -> list[dict[str, Any]]:
    """Pedidos por dia da semana e quantos dias de cada tipo existem no periodo."""
    linhas = conexao.execute(
        text(
            VENDAS
            + """
            , calendario AS (
                SELECT extract(dow FROM d)::int AS dia_semana, count(*) AS dias
                FROM generate_series(
                    CAST(:inicio AS date), CAST(:fim AS date), interval '1 day'
                ) AS g(d)
                GROUP BY 1
            ),
            pedidos AS (
                SELECT extract(dow FROM dia)::int AS dia_semana,
                       count(DISTINCT id_pedido) AS pedidos
                FROM venda
                GROUP BY 1
            )
            SELECT semana.dia_semana,
                   COALESCE(pedidos.pedidos, 0) AS pedidos,
                   COALESCE(calendario.dias, 0) AS dias
            FROM generate_series(0, 6) AS semana(dia_semana)
            LEFT JOIN calendario ON calendario.dia_semana = semana.dia_semana
            LEFT JOIN pedidos ON pedidos.dia_semana = semana.dia_semana
            ORDER BY semana.dia_semana
            """  # nosec B608
        ),
        _parametros(filtro, inicio, fim),
    ).mappings()
    return [dict(linha) for linha in linhas]


def pecas_mais_vendidas(
    conexao: Connection, filtro: Filtro, inicio: date, fim: date, *, limite: int
) -> list[dict[str, Any]]:
    linhas = conexao.execute(
        text(
            VENDAS
            + """
            SELECT id_produto,
                   produto AS nome,
                   categoria,
                   sum(quantidade) AS unidades,
                   sum(valor) AS faturamento
            FROM venda
            GROUP BY id_produto, produto, categoria
            ORDER BY unidades DESC, faturamento DESC, produto
            LIMIT :limite
            """  # nosec B608
        ),
        {**_parametros(filtro, inicio, fim), "limite": limite},
    ).mappings()
    return [dict(linha) for linha in linhas]


def categorias_de_produto(conexao: Connection) -> list[str]:
    linhas = conexao.execute(
        text(
            """
            SELECT DISTINCT categoria
            FROM produto
            WHERE ativo AND categoria IS NOT NULL AND length(trim(categoria)) > 0
            ORDER BY categoria
            """
        )
    ).scalars()
    return list(linhas)


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


# Reposicao: o saldo (da loja, ou somado na rede) contra o ritmo de venda dos ultimos 30 dias.
# Entra quem esta no minimo ou abaixo, ou tem menos de 21 dias de cobertura. Esgotadas primeiro; no
# resto, quem acaba antes. Pecas sem giro e acima do minimo nao aparecem (nao ha pressa).
REPOSICAO_DE = f"""
FROM (
    SELECT e.id_variacao, sum(e.quantidade) AS saldo, sum(e.estoque_minimo) AS minimo
    FROM estoque e
    WHERE CAST(:id_loja AS uuid) IS NULL OR e.id_loja = CAST(:id_loja AS uuid)
    GROUP BY e.id_variacao
) saldo
JOIN variacao_produto v ON v.id_variacao = saldo.id_variacao AND v.ativa
JOIN produto ON produto.id_produto = v.id_produto AND produto.ativo
LEFT JOIN (
    SELECT i.id_variacao, sum(i.quantidade)::numeric / {DIAS_DE_GIRO} AS giro_diario
    FROM pedido p
    JOIN status_pedido s ON s.id_status_pedido = p.id_status_pedido
    JOIN item_pedido i ON i.id_pedido = p.id_pedido
    WHERE s.codigo = ANY(CAST(:status_de_venda AS text[]))
      AND p.criado_em >= now() - interval '{DIAS_DE_GIRO} days'
      AND (CAST(:id_loja AS uuid) IS NULL OR p.id_loja = CAST(:id_loja AS uuid))
    GROUP BY i.id_variacao
) giro ON giro.id_variacao = saldo.id_variacao
CROSS JOIN LATERAL (
    SELECT CASE WHEN giro.giro_diario > 0 THEN saldo.saldo / giro.giro_diario END AS dias
) cobertura
WHERE (CAST(:categoria AS text) IS NULL OR produto.categoria = CAST(:categoria AS text))
  AND (
      saldo.saldo <= saldo.minimo
      OR cobertura.dias < {COBERTURA_CURTA_EM_DIAS}
  )
"""  # nosec B608


def reposicao(
    conexao: Connection, filtro: Filtro, *, limite: int
) -> tuple[int, list[dict[str, Any]]]:
    parametros = filtro.parametros()
    total = conexao.execute(text("SELECT count(*) " + REPOSICAO_DE), parametros).scalar_one()
    linhas = conexao.execute(
        text(
            """
            SELECT
                v.id_variacao,
                v.sku,
                produto.nome AS produto,
                v.cor,
                v.tamanho,
                produto.categoria,
                saldo.saldo::int AS saldo,
                saldo.minimo::int AS minimo,
                giro.giro_diario,
                cobertura.dias AS dias_cobertura,
                CASE
                    WHEN saldo.saldo = 0 THEN 'esgotada'
                    WHEN saldo.saldo <= saldo.minimo THEN 'abaixo_do_minimo'
                    ELSE 'cobertura_curta'
                END AS situacao
            """
            + REPOSICAO_DE
            + """
            ORDER BY (saldo.saldo = 0) DESC, cobertura.dias ASC NULLS LAST, saldo.saldo ASC, v.sku
            LIMIT :limite
            """
        ),
        {**parametros, "limite": limite},
    ).mappings()
    return int(total), [dict(linha) for linha in linhas]


LOJAS_DA_REDE = """
SELECT
    l.id_loja,
    l.codigo,
    l.nome,
    l.cidade,
    l.uf,
    l.endereco,
    (SELECT u.nome FROM usuario u JOIN tipo_usuario t USING (id_tipo_usuario)
     WHERE u.id_loja = l.id_loja AND u.ativo AND t.codigo = 'gerente_loja'
     ORDER BY u.criado_em, u.id_usuario LIMIT 1) AS gerente,
    (SELECT count(*) FROM usuario u WHERE u.id_loja = l.id_loja AND u.ativo) AS equipe,
    COALESCE((SELECT sum(e.quantidade) FROM estoque e WHERE e.id_loja = l.id_loja), 0)
        AS unidades_em_estoque,
    (SELECT count(*) FROM estoque e
     JOIN variacao_produto v ON v.id_variacao = e.id_variacao AND v.ativa
     WHERE e.id_loja = l.id_loja AND e.quantidade <= e.estoque_minimo) AS pecas_em_alerta,
    COALESCE((
        SELECT sum(i.valor_total)
        FROM pedido p
        JOIN status_pedido s ON s.id_status_pedido = p.id_status_pedido
        JOIN item_pedido i ON i.id_pedido = p.id_pedido
        WHERE p.id_loja = l.id_loja
          AND s.codigo = ANY(CAST(:status_de_venda AS text[]))
          AND p.criado_em >= now() - interval '30 days'
    ), 0) AS vendas_30_dias,
    (SELECT count(*) FROM atendimento a
     JOIN status_atendimento sa ON sa.id_status_atendimento = a.id_status_atendimento
     WHERE a.id_loja = l.id_loja AND sa.codigo NOT IN ('resolvido', 'encerrado', 'cancelado'))
        AS chamados_abertos
FROM loja l
WHERE l.ativa AND (CAST(:id_loja AS uuid) IS NULL OR l.id_loja = CAST(:id_loja AS uuid))
ORDER BY l.nome
"""


def lojas_da_rede(conexao: Connection, id_loja: UUID | None) -> list[dict[str, Any]]:
    """Cartao de cada loja visivel: gerente, equipe, estoque, vendas e chamados."""
    linhas = conexao.execute(
        text(LOJAS_DA_REDE),
        {"id_loja": str(id_loja) if id_loja else None, "status_de_venda": list(STATUS_DE_VENDA)},
    ).mappings()
    return [dict(linha) for linha in linhas]


def ajustes_para_aprovar(conexao: Connection, filtro: Filtro) -> int:
    return conexao.execute(
        text(
            """
            SELECT count(*) FROM ajuste_estoque
            WHERE status = 'pendente'
              AND (CAST(:id_loja AS uuid) IS NULL OR id_loja = CAST(:id_loja AS uuid))
            """
        ),
        {"id_loja": filtro.parametros()["id_loja"]},
    ).scalar_one()


def transferencias_aguardando(conexao: Connection, filtro: Filtro) -> int:
    """Transferencias que esperam uma acao da loja.

    Aceitar o que pediram a ela (origem) ou uma reposicao a rede pedida por outra loja, e
    confirmar o recebimento do que ja foi aceito para ela (destino). Sem loja (admin olhando a
    rede), conta tudo que esta solicitado ou em transito.
    """
    return conexao.execute(
        text(
            """
            SELECT count(*)
            FROM transferencia_estoque t
            JOIN status_transferencia_estoque s
                ON s.id_status_transferencia_estoque = t.id_status_transferencia_estoque
            WHERE (
                CAST(:id_loja AS uuid) IS NULL AND s.codigo IN ('solicitada', 'aceita')
                OR (
                    s.codigo = 'solicitada'
                    AND (
                        t.id_loja_origem = CAST(:id_loja AS uuid)
                        OR (t.id_loja_origem IS NULL
                            AND t.id_loja_destino <> CAST(:id_loja AS uuid))
                    )
                )
                OR (s.codigo = 'aceita' AND t.id_loja_destino = CAST(:id_loja AS uuid))
            )
            """
        ),
        {"id_loja": filtro.parametros()["id_loja"]},
    ).scalar_one()


def vendas_por_categoria(
    conexao: Connection, filtro: Filtro, inicio: date, fim: date
) -> list[dict[str, Any]]:
    linhas = conexao.execute(
        text(
            VENDAS
            + """
            SELECT COALESCE(categoria, 'Sem categoria') AS categoria,
                   sum(valor) AS faturamento
            FROM venda
            GROUP BY 1
            ORDER BY faturamento DESC, categoria
            """  # nosec B608
        ),
        _parametros(filtro, inicio, fim),
    ).mappings()
    return [dict(linha) for linha in linhas]


def vendas_por_loja(
    conexao: Connection, filtro: Filtro, inicio: date, fim: date
) -> list[dict[str, Any]]:
    linhas = conexao.execute(
        text(
            VENDAS
            + """
            SELECT
                id_loja,
                COALESCE(sum(valor), 0) AS faturamento,
                count(DISTINCT id_pedido) AS pedidos,
                COALESCE(sum(quantidade), 0) AS pecas,
                COALESCE(sum(valor) FILTER (WHERE canal_venda = 'online'), 0)
                    AS faturamento_online
            FROM venda
            WHERE id_loja IS NOT NULL
            GROUP BY id_loja
            """  # nosec B608
        ),
        _parametros(filtro, inicio, fim),
    ).mappings()
    return [dict(linha) for linha in linhas]


ESTOQUE_DE = """
FROM estoque e
JOIN variacao_produto v ON v.id_variacao = e.id_variacao AND v.ativa
JOIN produto ON produto.id_produto = v.id_produto AND produto.ativo
WHERE (CAST(:categoria AS text) IS NULL OR produto.categoria = CAST(:categoria AS text))
  AND (cardinality(CAST(:ids_loja AS uuid[])) = 0
       OR e.id_loja = ANY(CAST(:ids_loja AS uuid[])))
"""


# O trecho comum (FROM/WHERE) e fixo neste modulo; so os parametros nomeados recebem valores.
ESTOQUE_POR_LOJA = """
    SELECT e.id_loja,
           COALESCE(sum(e.quantidade), 0) AS unidades,
           count(*) FILTER (WHERE e.quantidade = 0) AS esgotadas
    __ESTOQUE_DE__
    GROUP BY e.id_loja
""".replace("__ESTOQUE_DE__", ESTOQUE_DE)  # nosec B608

# Posicao das lojas escolhidas (ou da rede) somada por peca: esgotada = saldo total zero.
ESTOQUE_TOTAL = """
    SELECT COALESCE(sum(saldo), 0) AS unidades,
           count(*) AS pecas,
           count(DISTINCT id_produto) AS produtos,
           count(*) FILTER (WHERE saldo = 0) AS esgotadas
    FROM (
        SELECT e.id_variacao, produto.id_produto, sum(e.quantidade) AS saldo
        __ESTOQUE_DE__
        GROUP BY e.id_variacao, produto.id_produto
    ) por_peca
""".replace("__ESTOQUE_DE__", ESTOQUE_DE)  # nosec B608


def estoque_por_loja(conexao: Connection, filtro: Filtro) -> list[dict[str, Any]]:
    linhas = conexao.execute(text(ESTOQUE_POR_LOJA), filtro.parametros()).mappings()
    return [dict(linha) for linha in linhas]


def estoque_total(conexao: Connection, filtro: Filtro) -> dict[str, Any]:
    return dict(conexao.execute(text(ESTOQUE_TOTAL), filtro.parametros()).mappings().one())


def lojas_ativas(conexao: Connection, ids_loja: tuple[UUID, ...]) -> list[dict[str, Any]]:
    linhas = conexao.execute(
        text(
            """
            SELECT id_loja, codigo, nome, cidade
            FROM loja
            WHERE ativa
              AND (cardinality(CAST(:ids_loja AS uuid[])) = 0
                   OR id_loja = ANY(CAST(:ids_loja AS uuid[])))
            ORDER BY nome
            """
        ),
        {"ids_loja": [str(i) for i in ids_loja]},
    ).mappings()
    return [dict(linha) for linha in linhas]
