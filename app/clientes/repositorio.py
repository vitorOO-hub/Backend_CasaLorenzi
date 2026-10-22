"""SQL da area de clientes do painel, em SQLAlchemy (`text` com parametros ligados).

Bandit B608: os textos SQL abaixo so juntam constantes deste modulo; todo valor vindo da
requisicao entra por parametro nomeado (:busca, :cid, ...), nunca por concatenacao.

Quem ve quem: o admin (sem filtro de loja) ve todos os clientes; equipe de loja ve os clientes com
pedido na loja ou com chamado no escopo dela. Compras e valores so sao calculados quando
`ver_compras` e verdadeiro (gerente e admin): para o atendente o banco nem faz a conta.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.chamados.repositorio import FINAIS, NO_ESCOPO, Escopo

LIMITE_DA_FICHA = 50

CTES = f"""
WITH ped AS (
    SELECT p.id_pedido, p.id_cliente, p.valor_total, sp.codigo AS status_codigo
    FROM pedido p
    JOIN status_pedido sp ON sp.id_status_pedido = p.id_status_pedido
    WHERE (CAST(:id_loja AS uuid) IS NULL OR p.id_loja = CAST(:id_loja AS uuid))
), cham AS (
    SELECT a.id_cliente, a.id_usuario_responsavel, st.codigo AS status_codigo, a.historico_vulto
    FROM atendimento a
    JOIN status_atendimento st ON st.id_status_atendimento = a.id_status_atendimento
    WHERE {NO_ESCOPO}
), base AS (
    SELECT
        cli.id_usuario AS id_cliente, cli.nome, cli.email, cli.telefone, cli.cidade,
        cli.criado_em AS cliente_desde,
        (SELECT count(*) FROM cham c WHERE c.id_cliente = cli.id_usuario) AS total_chamados,
        (SELECT count(*) FROM cham c
          WHERE c.id_cliente = cli.id_usuario AND NOT c.historico_vulto
            AND c.status_codigo <> ALL (CAST(:finais AS text[]))) AS chamados_em_aberto,
        (SELECT count(*) FROM cham c
          WHERE c.id_cliente = cli.id_usuario
            AND c.id_usuario_responsavel = CAST(:id_usuario AS uuid)) AS atendidos_por_mim,
        (SELECT count(*) FROM ped p WHERE p.id_cliente = cli.id_usuario) AS pedidos_no_escopo,
        CASE WHEN CAST(:ver_compras AS boolean) THEN
            (SELECT count(*) FROM ped p
              WHERE p.id_cliente = cli.id_usuario AND p.status_codigo <> 'cancelado')
        END AS compras,
        CASE WHEN CAST(:ver_compras AS boolean) THEN
            (SELECT COALESCE(sum(p.valor_total), 0) FROM ped p
              WHERE p.id_cliente = cli.id_usuario AND p.status_codigo <> 'cancelado')
        END AS total_gasto,
        cli.id_loja AS id_loja_cadastro,
        lc.nome AS loja_cadastro,
        -- Marca do cadastro: loja Vulto (inclui app e site da Vulto); o resto, sem loja ou loja
        -- Casa Lorenzi (inclui quem se cadastrou pelo site), e Casa Lorenzi.
        CASE WHEN lc.codigo LIKE 'LOJA-VULTO%' THEN 'vulto' ELSE 'casa_lorenzi' END
            AS marca_cadastro,
        pts.saldo AS saldo_pontos,
        -- Mesma regra do cartao Vulto+ (app/cliente/repositorio.py): creditos do ano corrente.
        CASE
            WHEN pts.saldo IS NULL THEN NULL
            WHEN pts.creditos_no_ano >= 5000 THEN 'ouro'
            WHEN pts.creditos_no_ano >= 2000 THEN 'prata'
            ELSE 'bronze'
        END AS categoria_vulto_mais
    FROM usuario cli
    JOIN tipo_usuario t ON t.id_tipo_usuario = cli.id_tipo_usuario
    LEFT JOIN loja lc ON lc.id_loja = cli.id_loja
    LEFT JOIN LATERAL (
        SELECT sum(m.pontos)::int AS saldo,
               COALESCE(sum(m.pontos) FILTER (
                   WHERE ((m.pontos > 0 AND m.tipo <> 'estorno')
                          OR (m.tipo = 'estorno' AND m.id_pedido IS NOT NULL))
                     AND m.ocorrido_em >= date_trunc('year', now() AT TIME ZONE 'America/Sao_Paulo')
               ), 0)::int AS creditos_no_ano
        FROM movimento_pontos m
        WHERE m.id_usuario = cli.id_usuario
        HAVING count(*) > 0
    ) pts ON true
    WHERE t.codigo = 'cliente' AND cli.ativo
)
"""  # nosec B608

VISIVEL = """
    (CAST(:id_loja AS uuid) IS NULL OR total_chamados > 0 OR pedidos_no_escopo > 0)
"""

BUSCA = """
    (
        CAST(:busca AS text) IS NULL
        OR nome ILIKE CAST(:busca AS text) ESCAPE '\\'
        OR email ILIKE CAST(:busca AS text) ESCAPE '\\'
        OR COALESCE(telefone, '') ILIKE CAST(:busca AS text) ESCAPE '\\'
    )
"""

# Fragmentos fixos escolhidos pelo codigo: o texto do usuario nunca vira SQL.
SECOES = {
    "todos": "",
    "com_aberto": "AND chamados_em_aberto > 0",
    "meus": "AND atendidos_por_mim > 0",
}

COLUNAS_ITEM = (
    "id_cliente, nome, email, telefone, cidade, cliente_desde, total_chamados, "
    "chamados_em_aberto, compras, total_gasto, id_loja_cadastro, loja_cadastro, saldo_pontos, "
    "categoria_vulto_mais"
)

# Filtros do Vulto+ (fixos, escolhidos pelo codigo). "sem_pontos": fora do programa.
FILTRO_DE_CATEGORIA = """
    AND (CAST(:categoria AS text) IS NULL
         OR (CAST(:categoria AS text) = 'sem_pontos' AND categoria_vulto_mais IS NULL)
         OR categoria_vulto_mais = CAST(:categoria AS text))
"""
FILTRO_DE_MARCA = """
    AND (CAST(:marca AS text) IS NULL OR marca_cadastro = CAST(:marca AS text))
"""
FILTRO_DE_LOJA_DE_CADASTRO = """
    AND (CAST(:id_loja_cadastro AS uuid) IS NULL
         OR id_loja_cadastro = CAST(:id_loja_cadastro AS uuid))
"""


def escapar_busca(termo: str | None) -> str | None:
    """Padrao do ILIKE ("%termo%"), com %, _ e barra invertida digitados tratados como letras."""
    termo = (termo or "").strip()
    if not termo:
        return None
    seguro = termo.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{seguro}%"


def _parametros(escopo: Escopo, *, ver_compras: bool, **extra: Any) -> dict[str, Any]:
    return {**escopo.parametros(), "finais": list(FINAIS), "ver_compras": ver_compras, **extra}


def listar(
    conexao: Connection,
    escopo: Escopo,
    *,
    ver_compras: bool,
    busca: str | None,
    secao: str,
    limit: int,
    offset: int,
    categoria: str | None = None,
    id_loja_cadastro: UUID | None = None,
    marca: str | None = None,
) -> tuple[int, list[dict[str, Any]]]:
    onde = (
        f"WHERE {VISIVEL} AND {BUSCA} {SECOES[secao]} "
        f"{FILTRO_DE_CATEGORIA} {FILTRO_DE_LOJA_DE_CADASTRO} {FILTRO_DE_MARCA}"
    )
    parametros = _parametros(
        escopo,
        ver_compras=ver_compras,
        busca=escapar_busca(busca),
        categoria=categoria,
        id_loja_cadastro=str(id_loja_cadastro) if id_loja_cadastro else None,
        marca=marca,
    )
    contagem = f"{CTES} SELECT count(*) FROM base {onde}"  # nosec B608
    total = conexao.execute(text(contagem), parametros).scalar_one()
    linhas = conexao.execute(
        text(
            f"""
            {CTES}
            SELECT {COLUNAS_ITEM} FROM base {onde}
            ORDER BY chamados_em_aberto DESC, nome, id_cliente
            LIMIT :limite OFFSET :deslocamento
            """  # nosec B608
        ),
        {**parametros, "limite": limit, "deslocamento": offset},
    ).mappings()
    return int(total), [dict(linha) for linha in linhas]


def ficha(
    conexao: Connection, escopo: Escopo, id_cliente: UUID, *, ver_compras: bool
) -> dict[str, Any] | None:
    parametros = _parametros(escopo, ver_compras=ver_compras, busca=None, cid=str(id_cliente))
    linha = (
        conexao.execute(
            text(
                f"""
                {CTES}
                SELECT {COLUNAS_ITEM} FROM base
                WHERE id_cliente = CAST(:cid AS uuid) AND {VISIVEL}
                """  # nosec B608
            ),
            parametros,
        )
        .mappings()
        .first()
    )
    if linha is None:
        return None
    base = dict(linha)

    chamados = [
        dict(c)
        for c in conexao.execute(
            text(
                f"""
                SELECT a.id_atendimento, a.protocolo, COALESCE(a.assunto, ct.nome) AS assunto,
                       ct.codigo AS categoria_codigo, ct.nome AS categoria_nome,
                       st.codigo AS status_codigo, st.nome AS status_nome, a.aberto_em,
                       a.historico_vulto
                FROM atendimento a
                JOIN status_atendimento st ON st.id_status_atendimento = a.id_status_atendimento
                JOIN categoria_atendimento ct
                    ON ct.id_categoria_atendimento = a.id_categoria_atendimento
                WHERE a.id_cliente = CAST(:cid AS uuid) AND {NO_ESCOPO}
                ORDER BY a.aberto_em DESC
                LIMIT {LIMITE_DA_FICHA}
                """  # nosec B608
            ),
            {**escopo.parametros(), "cid": str(id_cliente)},
        ).mappings()
    ]

    compras = None
    if ver_compras:
        compras = [
            dict(p)
            for p in conexao.execute(
                text(
                    f"""
                    SELECT p.id_pedido, p.numero_pedido, p.criado_em, lj.nome AS loja_nome,
                           p.valor_total, sp.codigo AS status_codigo, sp.nome AS status_nome
                    FROM pedido p
                    JOIN status_pedido sp ON sp.id_status_pedido = p.id_status_pedido
                    JOIN loja lj ON lj.id_loja = p.id_loja
                    WHERE p.id_cliente = CAST(:cid AS uuid)
                      AND (CAST(:id_loja AS uuid) IS NULL OR p.id_loja = CAST(:id_loja AS uuid))
                    ORDER BY p.criado_em DESC
                    LIMIT {LIMITE_DA_FICHA}
                    """  # nosec B608
                ),
                {"cid": str(id_cliente), "id_loja": escopo.parametros()["id_loja"]},
            ).mappings()
        ]
    return {"base": base, "chamados": chamados, "compras": compras}


RESGATES_DA_FICHA = 10


def resgates_e_loja_de_cadastro(conexao: Connection, id_cliente: UUID) -> dict[str, Any]:
    """Ultimos resgates de pontos do cliente e a loja em que ele se cadastrou."""
    loja = conexao.execute(
        text(
            """
            SELECT l.nome FROM usuario u LEFT JOIN loja l ON l.id_loja = u.id_loja
            WHERE u.id_usuario = CAST(:cid AS uuid)
            """
        ),
        {"cid": str(id_cliente)},
    ).scalar_one_or_none()
    resgates = conexao.execute(
        text(
            """
            SELECT r.resgatado_em, r.pontos, r.desconto, l.nome AS loja_nome, r.atendente,
                   r.observacao
            FROM resgate_pontos r
            LEFT JOIN loja l ON l.id_loja = r.id_loja
            WHERE r.id_usuario = CAST(:cid AS uuid)
            ORDER BY r.resgatado_em DESC, r.criado_em DESC
            LIMIT :limite
            """
        ),
        {"cid": str(id_cliente), "limite": RESGATES_DA_FICHA},
    ).mappings()
    return {"loja_cadastro": loja, "resgates": [dict(r) for r in resgates]}


def lojas_de_cadastro(conexao: Connection) -> list[dict[str, Any]]:
    """Lojas em que ha pelo menos um cliente cadastrado (filtro da lista de clientes)."""
    linhas = conexao.execute(
        text(
            """
            SELECT DISTINCT l.id_loja, l.nome
            FROM usuario u
            JOIN tipo_usuario t ON t.id_tipo_usuario = u.id_tipo_usuario AND t.codigo = 'cliente'
            JOIN loja l ON l.id_loja = u.id_loja
            ORDER BY l.nome
            """
        )
    ).mappings()
    return [dict(linha) for linha in linhas]
