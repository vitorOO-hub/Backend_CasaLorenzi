"""Consultas do dashboard de atendimento, em SQLAlchemy (`text` com parametros ligados).

Toda entrada do usuario entra por parametro nomeado; nenhum SQL e montado com texto vindo da
requisicao. A conexao da API ignora RLS, entao o escopo de loja vem sempre do `Filtro`, que o
service monta a partir do token.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

FUSO = "America/Sao_Paulo"
STATUS_FINALIZADOS = ("resolvido", "encerrado", "cancelado")


@dataclass(frozen=True)
class Filtro:
    id_loja: UUID | None = None
    canal: str | None = None
    categoria: str | None = None
    # Equipe de loja tambem atende os chamados sem loja (fila geral); o admin filtra a rede.
    incluir_sem_loja: bool = False
    # Varias lojas ao mesmo tempo (comparacao do admin); vazio = nao restringe por esta lista.
    ids_loja: tuple[UUID, ...] = ()

    def parametros(self) -> dict[str, Any]:
        return {
            "id_loja": str(self.id_loja) if self.id_loja else None,
            "ids_loja": [str(i) for i in self.ids_loja],
            "canal": self.canal,
            "categoria": self.categoria,
            "incluir_sem_loja": self.incluir_sem_loja,
        }


# Bandit B608: os textos SQL abaixo so juntam constantes deste modulo; todo valor vindo da
# requisicao entra por parametro nomeado (:inicio, :id_loja, ...), nunca por concatenacao.
#
# Chamados abertos no periodo, com a primeira resposta da equipe (primeira mensagem de quem nao
# e cliente). O filtro por data usa o fuso de Sao Paulo para o "dia" bater com o do front.
BASE = """
WITH base AS (
    SELECT
        a.id_atendimento,
        a.id_loja,
        a.aberto_em,
        (a.aberto_em AT TIME ZONE :fuso)::date AS dia,
        status.codigo AS status_codigo,
        canal.codigo AS canal_codigo,
        categoria.codigo AS categoria_codigo,
        resposta.primeira_resposta_em
    FROM atendimento a
    JOIN status_atendimento status ON status.id_status_atendimento = a.id_status_atendimento
    JOIN canal_atendimento canal ON canal.id_canal_atendimento = a.id_canal_atendimento
    JOIN categoria_atendimento categoria
        ON categoria.id_categoria_atendimento = a.id_categoria_atendimento
    LEFT JOIN LATERAL (
        SELECT min(m.enviada_em) AS primeira_resposta_em
        FROM mensagem m
        JOIN usuario autor ON autor.id_usuario = m.id_usuario_remetente
        JOIN tipo_usuario tipo ON tipo.id_tipo_usuario = autor.id_tipo_usuario
        WHERE m.id_atendimento = a.id_atendimento AND tipo.codigo <> 'cliente'
    ) resposta ON true
    WHERE a.aberto_em >= CAST(:inicio AS date)::timestamp AT TIME ZONE :fuso
      AND a.aberto_em < (CAST(:fim AS date) + 1)::timestamp AT TIME ZONE :fuso
      AND (
        (CAST(:id_loja AS uuid) IS NULL AND cardinality(CAST(:ids_loja AS uuid[])) = 0)
        OR a.id_loja = CAST(:id_loja AS uuid)
        OR a.id_loja = ANY(CAST(:ids_loja AS uuid[]))
        OR (CAST(:incluir_sem_loja AS boolean) AND a.id_loja IS NULL)
    )
      AND (CAST(:canal AS text) IS NULL OR canal.codigo = CAST(:canal AS text))
      AND (CAST(:categoria AS text) IS NULL OR categoria.codigo = CAST(:categoria AS text))
)
"""

# GREATEST ignora NULL (devolveria 0 para quem ainda nao foi respondido), por isso o FILTER.
HORAS_ATE_RESPOSTA = (
    "avg(greatest(extract(epoch FROM (primeira_resposta_em - aberto_em)), 0) / 3600.0)"
    " FILTER (WHERE primeira_resposta_em IS NOT NULL)"
)


def _parametros(filtro: Filtro, inicio: date, fim: date) -> dict[str, Any]:
    return {"fuso": FUSO, "inicio": inicio, "fim": fim, **filtro.parametros()}


def resumo(conexao: Connection, filtro: Filtro, inicio: date, fim: date) -> dict[str, Any]:
    linha = (
        conexao.execute(
            text(
                BASE
                + f"""
                SELECT
                    count(*) AS total,
                    count(*) FILTER (WHERE status_codigo IN ('resolvido', 'encerrado'))
                        AS resolvidos,
                    {HORAS_ATE_RESPOSTA} AS resposta_media_horas
                FROM base
                """  # nosec B608
            ),
            _parametros(filtro, inicio, fim),
        )
        .mappings()
        .one()
    )
    return dict(linha)


def volume_diario(
    conexao: Connection, filtro: Filtro, inicio: date, fim: date
) -> list[dict[str, Any]]:
    linhas = conexao.execute(
        text(
            BASE
            + """
            SELECT dias.dia::date AS data, count(base.id_atendimento) AS total
            FROM generate_series(
                CAST(:inicio AS date), CAST(:fim AS date), interval '1 day'
            ) AS dias(dia)
            LEFT JOIN base ON base.dia = dias.dia::date
            GROUP BY dias.dia
            ORDER BY dias.dia
            """  # nosec B608
        ),
        _parametros(filtro, inicio, fim),
    ).mappings()
    return [dict(linha) for linha in linhas]


def por_categoria(
    conexao: Connection, filtro: Filtro, inicio: date, fim: date
) -> list[dict[str, Any]]:
    linhas = conexao.execute(
        text(
            BASE
            + """
            SELECT c.codigo, c.nome, count(base.id_atendimento) AS total
            FROM categoria_atendimento c
            LEFT JOIN base ON base.categoria_codigo = c.codigo
            WHERE c.ativo
            GROUP BY c.codigo, c.nome, c.ordem
            ORDER BY c.ordem
            """  # nosec B608
        ),
        _parametros(filtro, inicio, fim),
    ).mappings()
    return [dict(linha) for linha in linhas]


def resposta_por_canal(
    conexao: Connection, filtro: Filtro, inicio: date, fim: date
) -> list[dict[str, Any]]:
    linhas = conexao.execute(
        text(
            BASE
            + f"""
            SELECT
                c.codigo,
                c.nome,
                count(base.id_atendimento) AS total,
                {HORAS_ATE_RESPOSTA} AS resposta_media_horas
            FROM canal_atendimento c
            LEFT JOIN base ON base.canal_codigo = c.codigo
            WHERE c.ativo
            GROUP BY c.codigo, c.nome, c.ordem
            ORDER BY c.ordem
            """  # nosec B608
        ),
        _parametros(filtro, inicio, fim),
    ).mappings()
    return [dict(linha) for linha in linhas]


def opcoes_de_canal(conexao: Connection) -> list[dict[str, Any]]:
    linhas = conexao.execute(
        text("SELECT codigo, nome FROM canal_atendimento WHERE ativo ORDER BY ordem")
    ).mappings()
    return [dict(linha) for linha in linhas]


def opcoes_de_categoria(conexao: Connection) -> list[dict[str, Any]]:
    linhas = conexao.execute(
        text("SELECT codigo, nome FROM categoria_atendimento WHERE ativo ORDER BY ordem")
    ).mappings()
    return [dict(linha) for linha in linhas]


def opcoes_de_loja(conexao: Connection, id_loja: UUID | None) -> list[dict[str, Any]]:
    """Todas as lojas ativas para o admin; so a do proprio usuario para os demais."""
    linhas = conexao.execute(
        text(
            """
            SELECT id_loja, nome
            FROM loja
            WHERE ativa AND (CAST(:id_loja AS uuid) IS NULL OR id_loja = CAST(:id_loja AS uuid))
            ORDER BY nome
            """
        ),
        {"id_loja": str(id_loja) if id_loja else None},
    ).mappings()
    return [dict(linha) for linha in linhas]


FILA_DE = """
FROM atendimento a
JOIN status_atendimento status ON status.id_status_atendimento = a.id_status_atendimento
JOIN canal_atendimento canal ON canal.id_canal_atendimento = a.id_canal_atendimento
JOIN categoria_atendimento categoria
    ON categoria.id_categoria_atendimento = a.id_categoria_atendimento
JOIN prioridade_atendimento prioridade
    ON prioridade.id_prioridade_atendimento = a.id_prioridade_atendimento
JOIN usuario cliente ON cliente.id_usuario = a.id_cliente
LEFT JOIN loja ON loja.id_loja = a.id_loja
WHERE status.codigo NOT IN ('resolvido', 'encerrado', 'cancelado')
  AND (
        CAST(:id_loja AS uuid) IS NULL
        OR a.id_loja = CAST(:id_loja AS uuid)
        OR (CAST(:incluir_sem_loja AS boolean) AND a.id_loja IS NULL)
    )
  AND (CAST(:canal AS text) IS NULL OR canal.codigo = CAST(:canal AS text))
  AND (CAST(:categoria AS text) IS NULL OR categoria.codigo = CAST(:categoria AS text))
"""


def contadores_da_fila(conexao: Connection, filtro: Filtro) -> dict[str, Any]:
    linha = (
        conexao.execute(
            text(
                """
                SELECT
                    count(*) AS total_aberto,
                    count(*) FILTER (WHERE status.codigo = 'aberto') AS sem_resposta,
                    count(*) FILTER (WHERE prioridade.codigo IN ('alta', 'urgente')) AS urgentes
                """
                + FILA_DE
            ),
            filtro.parametros(),
        )
        .mappings()
        .one()
    )
    return dict(linha)


def fila(conexao: Connection, filtro: Filtro, *, limit: int, offset: int) -> list[dict[str, Any]]:
    """Prioridade mais alta primeiro; dentro dela, os chamados mais antigos."""
    linhas = conexao.execute(
        text(
            """
            SELECT
                a.id_atendimento,
                COALESCE(a.assunto, categoria.nome) AS assunto,
                cliente.nome AS cliente_nome,
                canal.codigo AS canal_codigo,
                canal.nome AS canal,
                categoria.codigo AS categoria_codigo,
                categoria.nome AS categoria,
                prioridade.codigo AS prioridade_codigo,
                prioridade.nome AS prioridade,
                status.codigo AS status_codigo,
                status.nome AS status,
                a.aberto_em,
                a.id_loja,
                loja.nome AS loja_nome,
                (status.codigo = 'aberto') AS sem_resposta
            """
            + FILA_DE
            + """
            ORDER BY prioridade.ordem DESC, a.aberto_em ASC, a.id_atendimento
            LIMIT :limite OFFSET :deslocamento
            """
        ),
        {**filtro.parametros(), "limite": limit, "deslocamento": offset},
    ).mappings()
    return [dict(linha) for linha in linhas]


def resumo_por_loja(
    conexao: Connection, filtro: Filtro, inicio: date, fim: date
) -> list[dict[str, Any]]:
    """Chamados do periodo e primeira resposta media, uma linha por loja (comparacao do admin)."""
    linhas = conexao.execute(
        text(
            BASE
            + f"""
            SELECT
                id_loja,
                count(*) AS total,
                {HORAS_ATE_RESPOSTA} AS resposta_media_horas
            FROM base
            WHERE id_loja IS NOT NULL
            GROUP BY id_loja
            """  # nosec B608
        ),
        _parametros(filtro, inicio, fim),
    ).mappings()
    return [dict(linha) for linha in linhas]


def abertos_agora(conexao: Connection, ids_loja: tuple[UUID, ...]) -> list[dict[str, Any]]:
    """Chamados ainda nao finalizados hoje, por loja (id_loja nulo = fila geral sem loja)."""
    linhas = conexao.execute(
        text(
            """
            SELECT a.id_loja, count(*) AS total
            FROM atendimento a
            JOIN status_atendimento s ON s.id_status_atendimento = a.id_status_atendimento
            WHERE s.codigo <> ALL(CAST(:finalizados AS text[]))
              AND (cardinality(CAST(:ids_loja AS uuid[])) = 0
                   OR a.id_loja = ANY(CAST(:ids_loja AS uuid[])))
            GROUP BY a.id_loja
            """
        ),
        {"finalizados": list(STATUS_FINALIZADOS), "ids_loja": [str(i) for i in ids_loja]},
    ).mappings()
    return [dict(linha) for linha in linhas]
