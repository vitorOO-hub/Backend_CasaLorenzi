"""Operacoes de banco da tabela estoque (SQL parametrizado, psycopg)."""

from decimal import Decimal
from uuid import UUID

from app.estoque.erros import EstoqueComSaldo, EstoqueInsuficiente, RegistroNaoEncontrado


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
    with conexao.cursor() as cursor:
        cursor.execute(
            """
            SELECT *
            FROM estoque
            WHERE id_estoque = %s
            """,
            (id_estoque,),
        )
        return cursor.fetchone()


def listar_estoques(conexao) -> list[dict[str, object]]:
    with conexao.cursor() as cursor:
        cursor.execute(
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
            """
        )
        return [serializar_linha(linha) for linha in cursor.fetchall()]


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
    with conexao.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO estoque (id_loja, id_variacao, quantidade, estoque_minimo)
            VALUES (%s, %s, %s, %s)
            RETURNING *
            """,
            (id_loja, id_variacao, quantidade, estoque_minimo),
        )
        conexao.commit()
        return serializar_linha(cursor.fetchone())


def registrar_entrada(conexao, *, id_estoque: int | UUID, quantidade: int) -> dict[str, object]:
    with conexao.cursor() as cursor:
        cursor.execute(
            """
            UPDATE estoque
            SET quantidade = quantidade + %s,
                atualizado_em = now()
            WHERE id_estoque = %s
            RETURNING *
            """,
            (quantidade, id_estoque),
        )
        linha = cursor.fetchone()
        if not linha:
            conexao.rollback()
            raise RegistroNaoEncontrado
        conexao.commit()
        return serializar_linha(linha)


def registrar_saida(conexao, *, id_estoque: int | UUID, quantidade: int) -> dict[str, object]:
    with conexao.cursor() as cursor:
        cursor.execute(
            """
            UPDATE estoque
            SET quantidade = quantidade - %s,
                atualizado_em = now()
            WHERE id_estoque = %s
              AND quantidade >= %s
            RETURNING *
            """,
            (quantidade, id_estoque, quantidade),
        )
        linha = cursor.fetchone()
        if linha:
            conexao.commit()
            return serializar_linha(linha)

        if _buscar_por_id(conexao, id_estoque):
            conexao.rollback()
            raise EstoqueInsuficiente

        conexao.rollback()
        raise RegistroNaoEncontrado


def atualizar_estoque_minimo(
    conexao,
    *,
    id_estoque: int | UUID,
    estoque_minimo: int,
) -> dict[str, object]:
    with conexao.cursor() as cursor:
        cursor.execute(
            """
            UPDATE estoque
            SET estoque_minimo = %s,
                atualizado_em = now()
            WHERE id_estoque = %s
            RETURNING *
            """,
            (estoque_minimo, id_estoque),
        )
        linha = cursor.fetchone()
        if not linha:
            conexao.rollback()
            raise RegistroNaoEncontrado
        conexao.commit()
        return serializar_linha(linha)


def remover_estoque_sem_saldo(conexao, *, id_estoque: int | UUID) -> dict[str, object]:
    with conexao.cursor() as cursor:
        cursor.execute(
            """
            DELETE FROM estoque
            WHERE id_estoque = %s
              AND quantidade = 0
            RETURNING *
            """,
            (id_estoque,),
        )
        linha = cursor.fetchone()
        if linha:
            conexao.commit()
            return serializar_linha(linha)

        atual = _buscar_por_id(conexao, id_estoque)
        conexao.rollback()
        if atual:
            raise EstoqueComSaldo
        raise RegistroNaoEncontrado
