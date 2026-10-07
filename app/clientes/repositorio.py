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
    SELECT a.id_cliente, a.id_usuario_responsavel, st.codigo AS status_codigo
    FROM atendimento a
    JOIN status_atendimento st ON st.id_status_atendimento = a.id_status_atendimento
    WHERE {NO_ESCOPO}
), base AS (
    SELECT
        cli.id_usuario AS id_cliente, cli.nome, cli.email, cli.telefone, cli.cidade,
        cli.criado_em AS cliente_desde,
        (SELECT count(*) FROM cham c WHERE c.id_cliente = cli.id_usuario) AS total_chamados,
        (SELECT count(*) FROM cham c
          WHERE c.id_cliente = cli.id_usuario
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
        END AS total_gasto
    FROM usuario cli
    JOIN tipo_usuario t ON t.id_tipo_usuario = cli.id_tipo_usuario
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
    "chamados_em_aberto, compras, total_gasto"
)


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
) -> tuple[int, list[dict[str, Any]]]:
    onde = f"WHERE {VISIVEL} AND {BUSCA} {SECOES[secao]}"
    parametros = _parametros(escopo, ver_compras=ver_compras, busca=escapar_busca(busca))
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
                       st.codigo AS status_codigo, st.nome AS status_nome, a.aberto_em
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
