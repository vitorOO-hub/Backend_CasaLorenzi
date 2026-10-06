"""Operacoes SQL do modulo de compras."""

from app.compras.erros import ItemPedidoNaoEncontrado, PagamentoNaoEncontrado, PedidoNaoEncontrado
from app.core.repositorio import montar_insert, montar_update, serializar_linha, serializar_linhas


def listar_pedidos(conexao, *, limit: int, offset: int) -> list[dict[str, object]]:
    with conexao.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                p.*,
                l.nome AS loja,
                cliente.nome AS cliente,
                responsavel.nome AS usuario_responsavel,
                s.codigo AS status_codigo,
                s.nome AS status
            FROM pedido p
            JOIN loja l ON l.id_loja = p.id_loja
            JOIN usuario cliente ON cliente.id_usuario = p.id_cliente
            LEFT JOIN usuario responsavel ON responsavel.id_usuario = p.id_usuario_responsavel
            JOIN status_pedido s ON s.id_status_pedido = p.id_status_pedido
            ORDER BY p.criado_em DESC
            LIMIT %s OFFSET %s
            """,
            (limit, offset),
        )
        return serializar_linhas(cursor.fetchall())


def obter_pedido(conexao, id_pedido: object) -> dict[str, object]:
    with conexao.cursor() as cursor:
        cursor.execute("SELECT * FROM pedido WHERE id_pedido = %s", (id_pedido,))
        linha = cursor.fetchone()
        if not linha:
            raise PedidoNaoEncontrado
        return serializar_linha(linha)


def criar_pedido(conexao, dados: dict[str, object]) -> dict[str, object]:
    sql, parametros = montar_insert("pedido", dados)
    with conexao.cursor() as cursor:
        cursor.execute(sql, parametros)
        conexao.commit()
        return serializar_linha(cursor.fetchone())


def atualizar_pedido(conexao, id_pedido: object, dados: dict[str, object]) -> dict[str, object]:
    sql, parametros = montar_update(
        "pedido",
        "id_pedido",
        id_pedido,
        dados,
        coluna_data="atualizado_em",
    )
    with conexao.cursor() as cursor:
        cursor.execute(sql, parametros)
        linha = cursor.fetchone()
        if not linha:
            conexao.rollback()
            raise PedidoNaoEncontrado
        conexao.commit()
        return serializar_linha(linha)


def cancelar_pedido(conexao, id_pedido: object) -> dict[str, object]:
    with conexao.cursor() as cursor:
        cursor.execute(
            """
            UPDATE pedido
            SET id_status_pedido = (
                    SELECT id_status_pedido
                    FROM status_pedido
                    WHERE codigo = 'cancelado'
                ),
                atualizado_em = now()
            WHERE id_pedido = %s
            RETURNING *
            """,
            (id_pedido,),
        )
        linha = cursor.fetchone()
        if not linha:
            conexao.rollback()
            raise PedidoNaoEncontrado
        conexao.commit()
        return serializar_linha(linha)


def listar_itens_pedido(conexao, id_pedido: object) -> list[dict[str, object]]:
    with conexao.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                i.*,
                v.sku,
                v.cor,
                v.tamanho,
                p.nome AS produto
            FROM item_pedido i
            JOIN variacao_produto v ON v.id_variacao = i.id_variacao
            JOIN produto p ON p.id_produto = v.id_produto
            WHERE i.id_pedido = %s
            ORDER BY p.nome, v.cor, v.tamanho
            """,
            (id_pedido,),
        )
        return serializar_linhas(cursor.fetchall())


def obter_item_pedido(conexao, id_item_pedido: object) -> dict[str, object]:
    with conexao.cursor() as cursor:
        cursor.execute("SELECT * FROM item_pedido WHERE id_item_pedido = %s", (id_item_pedido,))
        linha = cursor.fetchone()
        if not linha:
            raise ItemPedidoNaoEncontrado
        return serializar_linha(linha)


def _recalcular_total_pedido(conexao, id_pedido: object) -> None:
    with conexao.cursor() as cursor:
        cursor.execute(
            """
            UPDATE pedido
            SET valor_total = (
                    SELECT COALESCE(SUM(valor_total), 0)
                    FROM item_pedido
                    WHERE id_pedido = %s
                ),
                atualizado_em = now()
            WHERE id_pedido = %s
            """,
            (id_pedido, id_pedido),
        )


def criar_item_pedido(conexao, id_pedido: object, dados: dict[str, object]) -> dict[str, object]:
    dados_com_pedido = {"id_pedido": id_pedido, **dados}
    sql, parametros = montar_insert("item_pedido", dados_com_pedido)
    with conexao.cursor() as cursor:
        cursor.execute(sql, parametros)
        linha = cursor.fetchone()
        _recalcular_total_pedido(conexao, id_pedido)
        conexao.commit()
        return serializar_linha(linha)


def atualizar_item_pedido(
    conexao,
    id_item_pedido: object,
    dados: dict[str, object],
) -> dict[str, object]:
    sql, parametros = montar_update("item_pedido", "id_item_pedido", id_item_pedido, dados)
    with conexao.cursor() as cursor:
        cursor.execute(sql, parametros)
        linha = cursor.fetchone()
        if not linha:
            conexao.rollback()
            raise ItemPedidoNaoEncontrado
        _recalcular_total_pedido(conexao, linha["id_pedido"])
        conexao.commit()
        return serializar_linha(linha)


def remover_item_pedido(conexao, id_item_pedido: object) -> dict[str, object]:
    with conexao.cursor() as cursor:
        cursor.execute("DELETE FROM item_pedido WHERE id_item_pedido = %s RETURNING *", (id_item_pedido,))
        linha = cursor.fetchone()
        if not linha:
            conexao.rollback()
            raise ItemPedidoNaoEncontrado
        _recalcular_total_pedido(conexao, linha["id_pedido"])
        conexao.commit()
        return serializar_linha(linha)


def listar_pagamentos_pedido(conexao, id_pedido: object) -> list[dict[str, object]]:
    with conexao.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                g.*,
                m.codigo AS metodo_codigo,
                m.nome AS metodo,
                s.codigo AS status_codigo,
                s.nome AS status
            FROM pagamento g
            JOIN metodo_pagamento m ON m.id_metodo_pagamento = g.id_metodo_pagamento
            JOIN status_pagamento s ON s.id_status_pagamento = g.id_status_pagamento
            WHERE g.id_pedido = %s
            ORDER BY g.tentativa
            """,
            (id_pedido,),
        )
        return serializar_linhas(cursor.fetchall())


def obter_pagamento(conexao, id_pagamento: object) -> dict[str, object]:
    with conexao.cursor() as cursor:
        cursor.execute("SELECT * FROM pagamento WHERE id_pagamento = %s", (id_pagamento,))
        linha = cursor.fetchone()
        if not linha:
            raise PagamentoNaoEncontrado
        return serializar_linha(linha)


def criar_pagamento(conexao, id_pedido: object, dados: dict[str, object]) -> dict[str, object]:
    sql, parametros = montar_insert("pagamento", {"id_pedido": id_pedido, **dados})
    with conexao.cursor() as cursor:
        cursor.execute(sql, parametros)
        conexao.commit()
        return serializar_linha(cursor.fetchone())


def atualizar_status_pagamento(
    conexao,
    id_pagamento: object,
    dados: dict[str, object],
) -> dict[str, object]:
    sql, parametros = montar_update("pagamento", "id_pagamento", id_pagamento, dados)
    with conexao.cursor() as cursor:
        cursor.execute(sql, parametros)
        linha = cursor.fetchone()
        if not linha:
            conexao.rollback()
            raise PagamentoNaoEncontrado
        conexao.commit()
        return serializar_linha(linha)
