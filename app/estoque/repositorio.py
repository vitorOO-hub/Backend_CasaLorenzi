"""Operacoes de banco da tabela estoque com SQLAlchemy Core."""

from decimal import Decimal
from uuid import UUID

from app.core.repositorio import buscar_todos, buscar_um, executar_sql
from app.estoque.erros import (
    EstoqueComSaldo,
    EstoqueInsuficiente,
    RegistroNaoEncontrado,
    TipoMovimentacaoEstoqueNaoEncontrado,
)


def normalizar_id(valor: object) -> int | UUID:
    if isinstance(valor, int) and not isinstance(valor, bool):
        return valor
    texto = str(valor).strip()
    if texto.isdigit():
        return int(texto)
    return UUID(texto)


def normalizar_quantidade(valor: object, *, nome: str = "quantidade", permite_zero: bool = False) -> int:
    if isinstance(valor, bool):
        raise ValueError(f"{nome} deve ser um numero inteiro")
    quantidade = int(valor)
    if permite_zero:
        if quantidade < 0:
            raise ValueError(f"{nome} nao pode ser negativa")
    elif quantidade <= 0:
        raise ValueError(f"{nome} deve ser maior que zero")
    return quantidade


def serializar_valor(valor: object) -> object:
    if isinstance(valor, UUID):
        return str(valor)
    if isinstance(valor, Decimal):
        return str(valor)
    if hasattr(valor, "isoformat"):
        return valor.isoformat()
    return valor


def serializar_linha(linha: dict[str, object]) -> dict[str, object]:
    return {chave: serializar_valor(valor) for chave, valor in linha.items()}


def _buscar_por_id(conexao, id_estoque: int | UUID) -> dict[str, object] | None:
    return buscar_um(
        conexao,
        """
        SELECT *
        FROM estoque
        WHERE id_estoque = %s
        """,
        (id_estoque,),
    )


def _buscar_por_id_para_atualizar(conexao, id_estoque: int | UUID) -> dict[str, object] | None:
    return buscar_um(
        conexao,
        """
        SELECT *
        FROM estoque
        WHERE id_estoque = %s
        FOR UPDATE
        """,
        (id_estoque,),
    )


def _buscar_tipo_movimentacao(conexao, codigo: str) -> object:
    linha = buscar_um(
        conexao,
        """
        SELECT id_tipo_movimentacao_estoque
        FROM tipo_movimentacao_estoque
        WHERE codigo = %s
          AND ativo
        """,
        (codigo,),
    )
    if not linha:
        raise TipoMovimentacaoEstoqueNaoEncontrado
    return linha["id_tipo_movimentacao_estoque"]


def _registrar_movimentacao(
    conexao,
    *,
    estoque: dict[str, object],
    codigo_tipo: str,
    id_usuario_responsavel: int | UUID,
    quantidade: int,
    quantidade_anterior: int,
    quantidade_posterior: int,
    motivo: str | None,
) -> None:
    id_tipo = _buscar_tipo_movimentacao(conexao, codigo_tipo)
    executar_sql(
        conexao,
        """
        INSERT INTO movimentacao_estoque (
            id_loja,
            id_variacao,
            id_usuario_responsavel,
            id_tipo_movimentacao_estoque,
            quantidade,
            quantidade_anterior,
            quantidade_posterior,
            motivo
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            estoque["id_loja"],
            estoque["id_variacao"],
            id_usuario_responsavel,
            id_tipo,
            quantidade,
            quantidade_anterior,
            quantidade_posterior,
            motivo,
        ),
    )


def _atualizar_quantidade_absoluta(
    conexao,
    *,
    id_estoque: int | UUID,
    quantidade_posterior: int,
) -> dict[str, object]:
    linha = executar_sql(
        conexao,
        """
        UPDATE estoque
        SET quantidade = %s,
            atualizado_em = now()
        WHERE id_estoque = %s
        RETURNING *
        """,
        (quantidade_posterior, id_estoque),
    ).mappings().first()
    if not linha:
        raise RegistroNaoEncontrado
    return dict(linha)


def _registrar_alteracao_com_historico(
    conexao,
    *,
    id_estoque: int | UUID,
    id_usuario_responsavel: int | UUID,
    quantidade: int,
    codigo_tipo: str,
    motivo: str | None,
) -> dict[str, object]:
    estoque = _buscar_por_id_para_atualizar(conexao, id_estoque)
    if not estoque:
        conexao.rollback()
        raise RegistroNaoEncontrado

    quantidade_anterior = int(estoque["quantidade"])
    if codigo_tipo in {"entrada", "ajuste_positivo"}:
        quantidade_posterior = quantidade_anterior + quantidade
    else:
        quantidade_posterior = quantidade_anterior - quantidade

    if quantidade_posterior < 0:
        conexao.rollback()
        raise EstoqueInsuficiente

    atualizado = _atualizar_quantidade_absoluta(
        conexao,
        id_estoque=id_estoque,
        quantidade_posterior=quantidade_posterior,
    )
    _registrar_movimentacao(
        conexao,
        estoque=estoque,
        codigo_tipo=codigo_tipo,
        id_usuario_responsavel=id_usuario_responsavel,
        quantidade=quantidade,
        quantidade_anterior=quantidade_anterior,
        quantidade_posterior=quantidade_posterior,
        motivo=motivo,
    )
    conexao.commit()
    return serializar_linha(atualizado)


def listar_estoques(conexao) -> list[dict[str, object]]:
    linhas = buscar_todos(
        conexao,
        """
        SELECT
            e.id_estoque,
            e.id_loja,
            l.nome AS loja,
            e.id_variacao,
            v.sku,
            p.nome AS produto,
            v.cor,
            v.tamanho,
            e.quantidade,
            e.estoque_minimo,
            CASE
                WHEN e.quantidade = 0 THEN 'Esgotado'
                WHEN e.quantidade <= e.estoque_minimo THEN 'Estoque baixo'
                ELSE 'OK'
            END AS status_estoque,
            e.atualizado_em
        FROM estoque e
        JOIN loja l ON l.id_loja = e.id_loja
        JOIN variacao_produto v ON v.id_variacao = e.id_variacao
        JOIN produto p ON p.id_produto = v.id_produto
        ORDER BY l.nome, p.nome, v.cor, v.tamanho
        """,
    )
    return [serializar_linha(linha) for linha in linhas]


def obter_estoque(conexao, id_estoque: int | UUID) -> dict[str, object]:
    linha = _buscar_por_id(conexao, id_estoque)
    if not linha:
        raise RegistroNaoEncontrado
    return serializar_linha(linha)


def criar_estoque(
    conexao,
    *,
    id_loja: int | UUID,
    id_variacao: int | UUID,
    quantidade: int,
    estoque_minimo: int,
) -> dict[str, object]:
    linha = executar_sql(
        conexao,
        """
        INSERT INTO estoque (id_loja, id_variacao, quantidade, estoque_minimo)
        VALUES (%s, %s, %s, %s)
        RETURNING *
        """,
        (id_loja, id_variacao, quantidade, estoque_minimo),
    ).mappings().first()
    conexao.commit()
    return serializar_linha(dict(linha))


def registrar_entrada_com_historico(
    conexao,
    *,
    id_estoque: int | UUID,
    id_usuario_responsavel: int | UUID,
    quantidade: int,
    motivo: str | None = None,
) -> dict[str, object]:
    return _registrar_alteracao_com_historico(
        conexao,
        id_estoque=id_estoque,
        id_usuario_responsavel=id_usuario_responsavel,
        quantidade=quantidade,
        codigo_tipo="entrada",
        motivo=motivo,
    )


def registrar_entrada(conexao, *, id_estoque: int | UUID, quantidade: int) -> dict[str, object]:
    linha = executar_sql(
        conexao,
        """
        UPDATE estoque
        SET quantidade = quantidade + %s,
            atualizado_em = now()
        WHERE id_estoque = %s
        RETURNING *
        """,
        (quantidade, id_estoque),
    ).mappings().first()
    if not linha:
        conexao.rollback()
        raise RegistroNaoEncontrado
    conexao.commit()
    return serializar_linha(dict(linha))


def registrar_saida(conexao, *, id_estoque: int | UUID, quantidade: int) -> dict[str, object]:
    linha = executar_sql(
        conexao,
        """
        UPDATE estoque
        SET quantidade = quantidade - %s,
            atualizado_em = now()
        WHERE id_estoque = %s
          AND quantidade >= %s
        RETURNING *
        """,
        (quantidade, id_estoque, quantidade),
    ).mappings().first()
    if linha:
        conexao.commit()
        return serializar_linha(dict(linha))

    if _buscar_por_id(conexao, id_estoque):
        conexao.rollback()
        raise EstoqueInsuficiente

    conexao.rollback()
    raise RegistroNaoEncontrado


def registrar_saida_com_historico(
    conexao,
    *,
    id_estoque: int | UUID,
    id_usuario_responsavel: int | UUID,
    quantidade: int,
    motivo: str | None = None,
) -> dict[str, object]:
    return _registrar_alteracao_com_historico(
        conexao,
        id_estoque=id_estoque,
        id_usuario_responsavel=id_usuario_responsavel,
        quantidade=quantidade,
        codigo_tipo="saida",
        motivo=motivo,
    )


def atualizar_estoque_minimo(
    conexao,
    *,
    id_estoque: int | UUID,
    estoque_minimo: int,
) -> dict[str, object]:
    linha = executar_sql(
        conexao,
        """
        UPDATE estoque
        SET estoque_minimo = %s,
            atualizado_em = now()
        WHERE id_estoque = %s
        RETURNING *
        """,
        (estoque_minimo, id_estoque),
    ).mappings().first()
    if not linha:
        conexao.rollback()
        raise RegistroNaoEncontrado
    conexao.commit()
    return serializar_linha(dict(linha))


def ajustar_inventario_com_historico(
    conexao,
    *,
    id_estoque: int | UUID,
    id_usuario_responsavel: int | UUID,
    quantidade_real: int,
    motivo: str | None = None,
) -> dict[str, object]:
    estoque = _buscar_por_id_para_atualizar(conexao, id_estoque)
    if not estoque:
        conexao.rollback()
        raise RegistroNaoEncontrado

    quantidade_anterior = int(estoque["quantidade"])
    diferenca = quantidade_real - quantidade_anterior
    if diferenca == 0:
        conexao.commit()
        return serializar_linha(estoque)

    codigo_tipo = "ajuste_positivo" if diferenca > 0 else "ajuste_negativo"
    quantidade_movimentada = abs(diferenca)
    atualizado = _atualizar_quantidade_absoluta(
        conexao,
        id_estoque=id_estoque,
        quantidade_posterior=quantidade_real,
    )
    _registrar_movimentacao(
        conexao,
        estoque=estoque,
        codigo_tipo=codigo_tipo,
        id_usuario_responsavel=id_usuario_responsavel,
        quantidade=quantidade_movimentada,
        quantidade_anterior=quantidade_anterior,
        quantidade_posterior=quantidade_real,
        motivo=motivo,
    )
    conexao.commit()
    return serializar_linha(atualizado)


def remover_estoque_sem_saldo(conexao, *, id_estoque: int | UUID) -> dict[str, object]:
    linha = executar_sql(
        conexao,
        """
        DELETE FROM estoque
        WHERE id_estoque = %s
          AND quantidade = 0
        RETURNING *
        """,
        (id_estoque,),
    ).mappings().first()
    if linha:
        conexao.commit()
        return serializar_linha(dict(linha))

    atual = _buscar_por_id(conexao, id_estoque)
    conexao.rollback()
    if atual:
        raise EstoqueComSaldo
    raise RegistroNaoEncontrado
