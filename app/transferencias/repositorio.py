"""Operacoes SQL do fluxo de transferencia e reposicao de estoque."""

from uuid import UUID

from app.core.repositorio import buscar_todos, buscar_um, executar_sql, serializar_linha, serializar_linhas
from app.transferencias.erros import (
    TransferenciaInvalida,
    TransferenciaJaProcessada,
    TransferenciaNaoEncontrada,
)


def _buscar_id_opcao(conexao, *, tabela: str, coluna_id: str, codigo: str) -> object:
    linha = buscar_um(
        conexao,
        f"""
        SELECT {coluna_id}
        FROM {tabela}
        WHERE codigo = %s
          AND ativo
        """,
        (codigo,),
    )
    if not linha:
        raise TransferenciaInvalida
    return linha[coluna_id]


def _buscar_id_usuario_por_auth(conexao, auth_user_id: int | UUID) -> object:
    linha = buscar_um(
        conexao,
        """
        SELECT id_usuario
        FROM usuario
        WHERE auth_user_id = %s
          AND ativo
        """,
        (auth_user_id,),
    )
    if not linha:
        raise TransferenciaInvalida
    return linha["id_usuario"]


def listar_transferencias(
    conexao,
    *,
    id_loja: int | UUID,
    recebidas: bool,
    limit: int,
    offset: int,
) -> list[dict[str, object]]:
    filtro_loja = "t.id_loja_origem = %s" if recebidas else "(t.id_loja_origem = %s OR t.id_loja_destino = %s)"
    parametros: tuple[object, ...]
    if recebidas:
        parametros = (id_loja, limit, offset)
    else:
        parametros = (id_loja, id_loja, limit, offset)

    return serializar_linhas(
        buscar_todos(
            conexao,
            f"""
            SELECT
                t.*,
                tipo.codigo AS tipo_codigo,
                tipo.nome AS tipo_transferencia,
                status.codigo AS status_codigo,
                status.nome AS status_transferencia,
                origem.nome AS loja_origem,
                destino.nome AS loja_destino,
                v.sku,
                v.cor,
                v.tamanho,
                p.nome AS produto,
                solicitante.nome AS usuario_solicitante,
                responsavel.nome AS usuario_responsavel
            FROM transferencia_estoque t
            JOIN tipo_transferencia_estoque tipo
                ON tipo.id_tipo_transferencia_estoque = t.id_tipo_transferencia_estoque
            JOIN status_transferencia_estoque status
                ON status.id_status_transferencia_estoque = t.id_status_transferencia_estoque
            LEFT JOIN loja origem ON origem.id_loja = t.id_loja_origem
            JOIN loja destino ON destino.id_loja = t.id_loja_destino
            JOIN variacao_produto v ON v.id_variacao = t.id_variacao
            JOIN produto p ON p.id_produto = v.id_produto
            JOIN usuario solicitante ON solicitante.id_usuario = t.id_usuario_solicitante
            LEFT JOIN usuario responsavel ON responsavel.id_usuario = t.id_usuario_responsavel
            WHERE {filtro_loja}
            ORDER BY t.solicitada_em DESC
            LIMIT %s OFFSET %s
            """,
            parametros,
        )
    )


def obter_transferencia(conexao, id_transferencia: int | UUID) -> dict[str, object]:
    linha = buscar_um(
        conexao,
        """
        SELECT *
        FROM transferencia_estoque
        WHERE id_transferencia_estoque = %s
        """,
        (id_transferencia,),
    )
    if not linha:
        raise TransferenciaNaoEncontrada
    return serializar_linha(linha)


def solicitar_transferencia(
    conexao,
    *,
    id_loja_origem: int | UUID,
    id_loja_destino: int | UUID,
    id_variacao: int | UUID,
    auth_user_id_solicitante: int | UUID,
    quantidade: int,
    observacao: str | None,
) -> dict[str, object]:
    if id_loja_origem == id_loja_destino:
        raise TransferenciaInvalida
    return _criar_solicitacao(
        conexao,
        tipo_codigo="transferencia",
        id_loja_origem=id_loja_origem,
        id_loja_destino=id_loja_destino,
        id_variacao=id_variacao,
        auth_user_id_solicitante=auth_user_id_solicitante,
        quantidade=quantidade,
        observacao=observacao,
    )


def solicitar_reposicao(
    conexao,
    *,
    id_loja_destino: int | UUID,
    id_variacao: int | UUID,
    auth_user_id_solicitante: int | UUID,
    quantidade: int,
    observacao: str | None,
) -> dict[str, object]:
    return _criar_solicitacao(
        conexao,
        tipo_codigo="reposicao_rede",
        id_loja_origem=None,
        id_loja_destino=id_loja_destino,
        id_variacao=id_variacao,
        auth_user_id_solicitante=auth_user_id_solicitante,
        quantidade=quantidade,
        observacao=observacao,
    )


def _criar_solicitacao(
    conexao,
    *,
    tipo_codigo: str,
    id_loja_origem: int | UUID | None,
    id_loja_destino: int | UUID,
    id_variacao: int | UUID,
    auth_user_id_solicitante: int | UUID,
    quantidade: int,
    observacao: str | None,
) -> dict[str, object]:
    id_tipo = _buscar_id_opcao(
        conexao,
        tabela="tipo_transferencia_estoque",
        coluna_id="id_tipo_transferencia_estoque",
        codigo=tipo_codigo,
    )
    id_status = _buscar_id_opcao(
        conexao,
        tabela="status_transferencia_estoque",
        coluna_id="id_status_transferencia_estoque",
        codigo="solicitada",
    )
    id_usuario_solicitante = _buscar_id_usuario_por_auth(conexao, auth_user_id_solicitante)
    linha = executar_sql(
        conexao,
        """
        INSERT INTO transferencia_estoque (
            id_tipo_transferencia_estoque,
            id_status_transferencia_estoque,
            id_loja_origem,
            id_loja_destino,
            id_variacao,
            id_usuario_solicitante,
            quantidade,
            observacao
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (
            id_tipo,
            id_status,
            id_loja_origem,
            id_loja_destino,
            id_variacao,
            id_usuario_solicitante,
            quantidade,
            observacao,
        ),
    ).mappings().first()
    conexao.commit()
    return serializar_linha(dict(linha))


def aceitar_transferencia(
    conexao,
    *,
    id_transferencia: int | UUID,
    id_loja_responsavel: int | UUID,
    auth_user_id_responsavel: int | UUID,
) -> dict[str, object]:
    id_status_aceita = _buscar_id_opcao(
        conexao,
        tabela="status_transferencia_estoque",
        coluna_id="id_status_transferencia_estoque",
        codigo="aceita",
    )
    id_status_solicitada = _buscar_id_opcao(
        conexao,
        tabela="status_transferencia_estoque",
        coluna_id="id_status_transferencia_estoque",
        codigo="solicitada",
    )
    id_usuario_responsavel = _buscar_id_usuario_por_auth(conexao, auth_user_id_responsavel)
    linha = executar_sql(
        conexao,
        """
        UPDATE transferencia_estoque
        SET id_status_transferencia_estoque = %s,
            id_usuario_responsavel = %s,
            aceita_em = now(),
            atualizada_em = now()
        WHERE id_transferencia_estoque = %s
          AND id_loja_origem = %s
          AND id_status_transferencia_estoque = %s
        RETURNING *
        """,
        (
            id_status_aceita,
            id_usuario_responsavel,
            id_transferencia,
            id_loja_responsavel,
            id_status_solicitada,
        ),
    ).mappings().first()
    if linha:
        conexao.commit()
        return serializar_linha(dict(linha))

    atual = buscar_um(
        conexao,
        """
        SELECT id_transferencia_estoque
        FROM transferencia_estoque
        WHERE id_transferencia_estoque = %s
        """,
        (id_transferencia,),
    )
    conexao.rollback()
    if not atual:
        raise TransferenciaNaoEncontrada
    raise TransferenciaJaProcessada
