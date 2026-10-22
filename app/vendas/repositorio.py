"""SQL das vendas em loja. Todo valor vindo da requisicao entra por parametro, nunca por texto."""

from typing import Any
from uuid import UUID

from sqlalchemy.engine import Connection

from app.core.repositorio import buscar_todos, buscar_um, executar_sql
from app.vendas.schemas import so_digitos

METODOS_NA_LOJA = ("cartao_credito", "cartao_debito", "pix", "dinheiro")
# Tabelas de apoio de que a venda precisa; so estes nomes entram no SQL (constantes daqui).
_APOIO = {
    "status_pedido": "id_status_pedido",
    "metodo_pagamento": "id_metodo_pagamento",
    "status_pagamento": "id_status_pagamento",
    "tipo_movimentacao_estoque": "id_tipo_movimentacao_estoque",
}
_ESC = "ESCAPE '\\'"


def mascarar_cpf(cpf: str | None) -> str:
    return f"***.***.***-{cpf[-2:]}" if cpf and len(cpf) >= 2 else "***.***.***-**"


def escapar_busca(termo: str | None) -> str | None:
    """Padrao do ILIKE ("%termo%"), com %, _ e barra digitados tratados como letras."""
    termo = (termo or "").strip()
    if not termo:
        return None
    seguro = termo.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{seguro}%"


# ------------------------------------------------------------------ clientes


def _filtro_clientes(busca: str | None) -> tuple[str, tuple[Any, ...]]:
    padrao = escapar_busca(busca)
    if padrao is None:
        return "TRUE", ()
    digitos = so_digitos(busca or "")
    return (
        f"(u.nome ILIKE %s {_ESC} OR COALESCE(u.email, '') ILIKE %s {_ESC} "
        f"OR COALESCE(u.telefone, '') ILIKE %s {_ESC} "
        "OR (CAST(%s AS text) <> '' AND u.documento = %s))",
        (padrao, padrao, padrao, digitos, digitos),
    )


_CLIENTES = """
    FROM usuario u
    JOIN tipo_usuario t ON t.id_tipo_usuario = u.id_tipo_usuario
    WHERE t.codigo = 'cliente' AND u.ativo AND u.documento IS NOT NULL AND {filtro}
"""


def listar_clientes(
    conexao: Connection, busca: str | None, *, limit: int, offset: int
) -> tuple[int, list[dict[str, Any]]]:
    filtro, parametros = _filtro_clientes(busca)
    base = _CLIENTES.format(filtro=filtro)
    total = buscar_um(conexao, f"SELECT count(*) AS n {base}", parametros)  # nosec B608
    linhas = buscar_todos(
        conexao,
        f"""
        SELECT u.id_usuario AS id_cliente, u.nome, u.documento AS cpf, u.email, u.telefone,
               u.cidade, u.criado_em AS cliente_desde
        {base}
        ORDER BY u.nome, u.id_usuario
        LIMIT %s OFFSET %s
        """,  # nosec B608
        (*parametros, limit, offset),
    )
    return int(total["n"]) if total else 0, linhas


def cliente_por_cpf(conexao: Connection, cpf: str) -> dict[str, Any] | None:
    return buscar_um(
        conexao,
        """
        SELECT u.id_usuario AS id_cliente, u.nome, u.documento AS cpf, u.email, u.telefone
        FROM usuario u
        JOIN tipo_usuario t ON t.id_tipo_usuario = u.id_tipo_usuario
        WHERE t.codigo = 'cliente' AND u.ativo AND u.documento = %s
        """,
        (cpf,),
    )


# -------------------------------------------------------------------- vendas

_VENDAS = """
    FROM pedido p
    JOIN loja l ON l.id_loja = p.id_loja
    JOIN status_pedido sp ON sp.id_status_pedido = p.id_status_pedido
    JOIN usuario c ON c.id_usuario = p.id_cliente
    LEFT JOIN usuario v ON v.id_usuario = p.id_usuario_responsavel
    WHERE {filtro}
"""
_COLUNAS_VENDA = """
    p.id_pedido, p.numero_pedido, p.criado_em, p.canal_venda, p.valor_total, p.observacao,
    l.nome AS loja, c.nome AS cliente, c.documento AS cliente_cpf, v.nome AS vendedor,
    sp.codigo AS status_codigo, sp.nome AS status,
    (SELECT COALESCE(sum(ip.quantidade), 0) FROM item_pedido ip
      WHERE ip.id_pedido = p.id_pedido)::int AS pecas
"""


def _filtro_vendas(busca: str | None) -> tuple[str, tuple[Any, ...]]:
    padrao = escapar_busca(busca)
    if padrao is None:
        return "TRUE", ()
    digitos = so_digitos(busca or "")
    return (
        f"(p.numero_pedido ILIKE %s {_ESC} OR c.nome ILIKE %s {_ESC} "
        "OR (CAST(%s AS text) <> '' AND c.documento = %s))",
        (padrao, padrao, digitos, digitos),
    )


def listar_vendas(
    conexao: Connection, busca: str | None, *, limit: int, offset: int
) -> tuple[int, list[dict[str, Any]]]:
    filtro, parametros = _filtro_vendas(busca)
    base = _VENDAS.format(filtro=filtro)
    total = buscar_um(conexao, f"SELECT count(*) AS n {base}", parametros)  # nosec B608
    linhas = buscar_todos(
        conexao,
        f"""
        SELECT {_COLUNAS_VENDA}
        {base}
        ORDER BY p.criado_em DESC, p.id_pedido
        LIMIT %s OFFSET %s
        """,  # nosec B608
        (*parametros, limit, offset),
    )
    return int(total["n"]) if total else 0, linhas


def venda_por_id(conexao: Connection, id_pedido: UUID) -> dict[str, Any] | None:
    venda = buscar_um(
        conexao,
        f"SELECT {_COLUNAS_VENDA} {_VENDAS.format(filtro='p.id_pedido = %s')}",  # nosec B608
        (id_pedido,),
    )
    if venda is None:
        return None
    venda["itens_da_venda"] = buscar_todos(
        conexao,
        """
        SELECT va.sku, pr.nome AS produto, va.cor, va.tamanho, ip.quantidade,
               ip.preco_unitario, (ip.quantidade * ip.preco_unitario) AS valor_total
        FROM item_pedido ip
        JOIN variacao_produto va ON va.id_variacao = ip.id_variacao
        JOIN produto pr ON pr.id_produto = va.id_produto
        WHERE ip.id_pedido = %s
        ORDER BY pr.nome, va.cor, va.tamanho
        """,
        (id_pedido,),
    )
    pagamento = buscar_um(
        conexao,
        """
        SELECT mp.nome FROM pagamento g
        JOIN metodo_pagamento mp ON mp.id_metodo_pagamento = g.id_metodo_pagamento
        WHERE g.id_pedido = %s ORDER BY g.tentativa DESC LIMIT 1
        """,
        (id_pedido,),
    )
    venda["metodo_pagamento"] = pagamento["nome"] if pagamento else None
    return venda


# ----------------------------------------------------------- apoio da venda


def metodos(conexao: Connection) -> list[dict[str, Any]]:
    return buscar_todos(
        conexao,
        "SELECT codigo, nome FROM metodo_pagamento WHERE ativo AND codigo = ANY(%s) ORDER BY ordem",
        (list(METODOS_NA_LOJA),),
    )


def nome_da_loja(conexao: Connection, id_loja: UUID) -> str | None:
    linha = buscar_um(conexao, "SELECT nome FROM loja WHERE id_loja = %s AND ativa", (id_loja,))
    return linha["nome"] if linha else None


def pecas_da_loja(
    conexao: Connection, id_loja: UUID, busca: str | None, *, limit: int
) -> list[dict[str, Any]]:
    padrao = escapar_busca(busca)
    filtro = ""
    parametros: tuple[Any, ...] = (id_loja,)
    if padrao:
        filtro = f"AND (va.sku ILIKE %s {_ESC} OR pr.nome ILIKE %s {_ESC} OR va.ean = %s)"
        parametros = (id_loja, padrao, padrao, (busca or "").strip())
    return buscar_todos(
        conexao,
        f"""
        SELECT va.id_variacao, va.sku, pr.nome AS produto, va.cor, va.tamanho,
               va.preco_venda, e.quantidade AS disponivel
        FROM estoque e
        JOIN variacao_produto va ON va.id_variacao = e.id_variacao
        JOIN produto pr ON pr.id_produto = va.id_produto
        WHERE e.id_loja = %s AND e.quantidade > 0 AND va.ativa AND pr.ativo {filtro}
        ORDER BY pr.nome, va.cor, va.tamanho
        LIMIT %s
        """,  # nosec B608
        (*parametros, limit),
    )


def id_de_apoio(conexao: Connection, tabela: str, codigo: str) -> UUID | None:
    coluna = _APOIO[tabela]
    linha = buscar_um(
        conexao,
        f"SELECT {coluna} AS id FROM {tabela} WHERE codigo = %s AND ativo",  # nosec B608
        (codigo,),
    )
    return linha["id"] if linha else None


def venda_da_chave(conexao: Connection, id_vendedor: UUID, chave: str) -> UUID | None:
    linha = buscar_um(
        conexao,
        """
        SELECT p.id_pedido FROM pedido p
        JOIN pagamento g ON g.id_pedido = p.id_pedido
        WHERE p.id_usuario_responsavel = %s AND g.transacao_externa_id = %s
        ORDER BY p.criado_em DESC LIMIT 1
        """,
        (id_vendedor, chave),
    )
    return linha["id_pedido"] if linha else None


def travar_peca(conexao: Connection, id_loja: UUID, id_variacao: UUID) -> dict[str, Any] | None:
    """Peca ativa com linha de estoque nesta loja, travada ate o fim da transacao."""
    return buscar_um(
        conexao,
        """
        SELECT e.quantidade, va.sku, va.preco_venda
        FROM estoque e
        JOIN variacao_produto va ON va.id_variacao = e.id_variacao
        JOIN produto pr ON pr.id_produto = va.id_produto
        WHERE e.id_loja = %s AND e.id_variacao = %s AND va.ativa AND pr.ativo
        FOR UPDATE OF e
        """,
        (id_loja, id_variacao),
    )


def inserir_pedido(conexao: Connection, valores: tuple[Any, ...]) -> UUID:
    linha = buscar_um(
        conexao,
        """
        INSERT INTO pedido (numero_pedido, id_loja, id_cliente, id_usuario_responsavel,
                            id_status_pedido, canal_venda, valor_total, observacao)
        VALUES (%s, %s, %s, %s, %s, 'loja', %s, %s)
        RETURNING id_pedido
        """,
        valores,
    )
    assert linha is not None
    return linha["id_pedido"]


def baixar_item(
    conexao: Connection,
    *,
    id_pedido: UUID,
    id_loja: UUID,
    id_variacao: UUID,
    id_vendedor: UUID,
    id_tipo_venda: UUID,
    quantidade: int,
    anterior: int,
    preco: Any,
    numero: str,
) -> None:
    posterior = anterior - quantidade
    executar_sql(
        conexao,
        "INSERT INTO item_pedido (id_pedido, id_variacao, quantidade, preco_unitario) "
        "VALUES (%s, %s, %s, %s)",
        (id_pedido, id_variacao, quantidade, preco),
    )
    executar_sql(
        conexao,
        "UPDATE estoque SET quantidade = %s, atualizado_em = now() "
        "WHERE id_loja = %s AND id_variacao = %s",
        (posterior, id_loja, id_variacao),
    )
    executar_sql(
        conexao,
        """
        INSERT INTO movimentacao_estoque (
            id_loja, id_variacao, id_pedido, id_usuario_responsavel,
            id_tipo_movimentacao_estoque, quantidade, quantidade_anterior,
            quantidade_posterior, motivo)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            id_loja,
            id_variacao,
            id_pedido,
            id_vendedor,
            id_tipo_venda,
            quantidade,
            anterior,
            posterior,
            f"Venda em loja {numero}.",
        ),
    )


def inserir_pagamento(
    conexao: Connection,
    *,
    id_pedido: UUID,
    id_metodo: UUID,
    id_status: UUID,
    valor: Any,
    chave: str,
) -> None:
    executar_sql(
        conexao,
        """
        INSERT INTO pagamento (id_pedido, tentativa, id_metodo_pagamento, id_status_pagamento,
                               valor, transacao_externa_id, processado_em)
        VALUES (%s, 1, %s, %s, %s, %s, now())
        """,
        (id_pedido, id_metodo, id_status, valor, chave),
    )
