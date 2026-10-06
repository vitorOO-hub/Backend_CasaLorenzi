"""Operacoes SQL da tabela movimentacao_estoque."""

from app.core.repositorio import montar_insert, serializar_linha, serializar_linhas
from app.movimentacoes.erros import MovimentacaoNaoEncontrada


def listar_movimentacoes(conexao, *, limit: int, offset: int) -> list[dict[str, object]]:
    with conexao.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                m.*,
                l.nome AS loja,
                v.sku,
                p.nome AS produto,
                t.codigo AS tipo_codigo,
                t.nome AS tipo_movimentacao,
                u.nome AS usuario_responsavel
            FROM movimentacao_estoque m
            JOIN loja l ON l.id_loja = m.id_loja
            JOIN variacao_produto v ON v.id_variacao = m.id_variacao
            JOIN produto p ON p.id_produto = v.id_produto
            JOIN tipo_movimentacao_estoque t
                ON t.id_tipo_movimentacao_estoque = m.id_tipo_movimentacao_estoque
            LEFT JOIN usuario u ON u.id_usuario = m.id_usuario_responsavel
            ORDER BY m.criada_em DESC
            LIMIT %s OFFSET %s
            """,
            (limit, offset),
        )
        return serializar_linhas(cursor.fetchall())


def obter_movimentacao(conexao, id_movimentacao: object) -> dict[str, object]:
    with conexao.cursor() as cursor:
        cursor.execute(
            "SELECT * FROM movimentacao_estoque WHERE id_movimentacao_estoque = %s",
            (id_movimentacao,),
        )
        linha = cursor.fetchone()
        if not linha:
            raise MovimentacaoNaoEncontrada
        return serializar_linha(linha)


def criar_movimentacao(conexao, dados: dict[str, object]) -> dict[str, object]:
    sql, parametros = montar_insert("movimentacao_estoque", dados)
    with conexao.cursor() as cursor:
        cursor.execute(sql, parametros)
        conexao.commit()
        return serializar_linha(cursor.fetchone())
