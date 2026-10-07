"""Operacoes SQL do modulo de atendimento."""

from app.atendimento.erros import AtendimentoNaoEncontrado
from app.core.repositorio import (
    buscar_todos,
    buscar_um,
    executar_sql,
    montar_insert,
    montar_update,
    serializar_linha,
    serializar_linhas,
)


SELECT_ATENDIMENTO = """
SELECT
    a.*,
    cliente.nome AS cliente,
    responsavel.nome AS usuario_responsavel,
    p.numero_pedido,
    canal.codigo AS canal_codigo,
    canal.nome AS canal,
    categoria.codigo AS categoria_codigo,
    categoria.nome AS categoria,
    prioridade.codigo AS prioridade_codigo,
    prioridade.nome AS prioridade,
    status.codigo AS status_codigo,
    status.nome AS status
FROM atendimento a
JOIN usuario cliente ON cliente.id_usuario = a.id_cliente
LEFT JOIN usuario responsavel ON responsavel.id_usuario = a.id_usuario_responsavel
LEFT JOIN pedido p ON p.id_pedido = a.id_pedido
JOIN canal_atendimento canal ON canal.id_canal_atendimento = a.id_canal_atendimento
JOIN categoria_atendimento categoria
    ON categoria.id_categoria_atendimento = a.id_categoria_atendimento
JOIN prioridade_atendimento prioridade
    ON prioridade.id_prioridade_atendimento = a.id_prioridade_atendimento
JOIN status_atendimento status ON status.id_status_atendimento = a.id_status_atendimento
"""


def listar_opcoes(conexao, tabela: str, *, limit: int, offset: int) -> list[dict[str, object]]:
    return serializar_linhas(
        buscar_todos(
            conexao,
            f"""
            SELECT *
            FROM {tabela}
            ORDER BY ordem, nome
            LIMIT %s OFFSET %s
            """,
            (limit, offset),
        )
    )


def listar_atendimentos(conexao, *, limit: int, offset: int) -> list[dict[str, object]]:
    return serializar_linhas(
        buscar_todos(
            conexao,
            f"""
            {SELECT_ATENDIMENTO}
            ORDER BY a.aberto_em DESC
            LIMIT %s OFFSET %s
            """,
            (limit, offset),
        )
    )


def obter_atendimento(conexao, id_atendimento: object) -> dict[str, object]:
    linha = buscar_um(
        conexao,
        f"""
        {SELECT_ATENDIMENTO}
        WHERE a.id_atendimento = %s
        """,
        (id_atendimento,),
    )
    if not linha:
        raise AtendimentoNaoEncontrado
    return serializar_linha(linha)


def criar_atendimento(conexao, dados: dict[str, object]) -> dict[str, object]:
    sql, parametros = montar_insert("atendimento", dados)
    linha = executar_sql(conexao, sql, parametros).mappings().first()
    conexao.commit()
    return serializar_linha(dict(linha))


def atualizar_atendimento(
    conexao,
    id_atendimento: object,
    dados: dict[str, object],
) -> dict[str, object]:
    sql, parametros = montar_update(
        "atendimento",
        "id_atendimento",
        id_atendimento,
        dados,
        coluna_data="atualizado_em",
    )
    linha = executar_sql(conexao, sql, parametros).mappings().first()
    if not linha:
        conexao.rollback()
        raise AtendimentoNaoEncontrado
    conexao.commit()
    return serializar_linha(dict(linha))


def listar_mensagens(conexao, id_atendimento: object) -> list[dict[str, object]]:
    obter_atendimento(conexao, id_atendimento)
    return serializar_linhas(
        buscar_todos(
            conexao,
            """
            SELECT
                m.*,
                u.nome AS remetente,
                t.codigo AS tipo_usuario_codigo,
                t.nome AS tipo_usuario
            FROM mensagem m
            JOIN usuario u ON u.id_usuario = m.id_usuario_remetente
            JOIN tipo_usuario t ON t.id_tipo_usuario = u.id_tipo_usuario
            WHERE m.id_atendimento = %s
            ORDER BY m.enviada_em
            """,
            (id_atendimento,),
        )
    )


def criar_mensagem(
    conexao,
    id_atendimento: object,
    dados: dict[str, object],
) -> dict[str, object]:
    obter_atendimento(conexao, id_atendimento)
    sql, parametros = montar_insert("mensagem", {"id_atendimento": id_atendimento, **dados})
    linha = executar_sql(conexao, sql, parametros).mappings().first()
    conexao.commit()
    return serializar_linha(dict(linha))


def listar_itens_atendimento(conexao, id_atendimento: object) -> list[dict[str, object]]:
    obter_atendimento(conexao, id_atendimento)
    return serializar_linhas(
        buscar_todos(
            conexao,
            """
            SELECT
                ai.*,
                i.id_pedido,
                i.id_variacao,
                i.quantidade,
                i.preco_unitario,
                i.valor_total,
                v.sku,
                v.cor,
                v.tamanho,
                p.nome AS produto
            FROM atendimento_item ai
            JOIN item_pedido i ON i.id_item_pedido = ai.id_item_pedido
            JOIN variacao_produto v ON v.id_variacao = i.id_variacao
            JOIN produto p ON p.id_produto = v.id_produto
            WHERE ai.id_atendimento = %s
            ORDER BY p.nome, v.cor, v.tamanho
            """,
            (id_atendimento,),
        )
    )


def vincular_item_atendimento(
    conexao,
    id_atendimento: object,
    dados: dict[str, object],
) -> dict[str, object]:
    obter_atendimento(conexao, id_atendimento)
    sql, parametros = montar_insert(
        "atendimento_item",
        {"id_atendimento": id_atendimento, **dados},
    )
    linha = executar_sql(conexao, sql, parametros).mappings().first()
    conexao.commit()
    return serializar_linha(dict(linha))


def criar_avaliacao(
    conexao,
    id_atendimento: object,
    dados: dict[str, object],
) -> dict[str, object]:
    obter_atendimento(conexao, id_atendimento)
    sql, parametros = montar_insert(
        "avaliacao_atendimento",
        {"id_atendimento": id_atendimento, **dados},
    )
    linha = executar_sql(conexao, sql, parametros).mappings().first()
    conexao.commit()
    return serializar_linha(dict(linha))
