"""Operacoes SQL do modulo administrativo."""

from app.admin.erros import RegistroAdminNaoEncontrado
from app.core.repositorio import (
    buscar_todos,
    buscar_um,
    executar_sql,
    montar_insert,
    montar_update,
    serializar_linha,
    serializar_linhas,
)


def _listar(conexao, sql: str, parametros: tuple[object, ...]) -> list[dict[str, object]]:
    return serializar_linhas(buscar_todos(conexao, sql, parametros))


def _obter_por_id(conexao, tabela: str, coluna_id: str, id_registro: object, recurso: str):
    linha = buscar_um(conexao, f"SELECT * FROM {tabela} WHERE {coluna_id} = %s", (id_registro,))
    if not linha:
        raise RegistroAdminNaoEncontrado(recurso)
    return serializar_linha(linha)


def _criar(conexao, tabela: str, dados: dict[str, object]) -> dict[str, object]:
    sql, parametros = montar_insert(tabela, dados)
    linha = executar_sql(conexao, sql, parametros).mappings().first()
    conexao.commit()
    return serializar_linha(dict(linha))


def _atualizar(
    conexao,
    tabela: str,
    coluna_id: str,
    id_registro: object,
    dados: dict[str, object],
    recurso: str,
    *,
    coluna_data: str | None = None,
) -> dict[str, object]:
    sql, parametros = montar_update(
        tabela,
        coluna_id,
        id_registro,
        dados,
        coluna_data=coluna_data,
    )
    linha = executar_sql(conexao, sql, parametros).mappings().first()
    if not linha:
        conexao.rollback()
        raise RegistroAdminNaoEncontrado(recurso)
    conexao.commit()
    return serializar_linha(dict(linha))


def listar_lojas(conexao, *, limit: int, offset: int) -> list[dict[str, object]]:
    return _listar(
        conexao,
        """
        SELECT *
        FROM loja
        ORDER BY nome
        LIMIT %s OFFSET %s
        """,
        (limit, offset),
    )


def obter_loja(conexao, id_loja: object) -> dict[str, object]:
    return _obter_por_id(conexao, "loja", "id_loja", id_loja, "Loja")


def criar_loja(conexao, dados: dict[str, object]) -> dict[str, object]:
    return _criar(conexao, "loja", dados)


def atualizar_loja(conexao, id_loja: object, dados: dict[str, object]) -> dict[str, object]:
    return _atualizar(conexao, "loja", "id_loja", id_loja, dados, "Loja", coluna_data="atualizada_em")


def desativar_loja(conexao, id_loja: object) -> dict[str, object]:
    return atualizar_loja(conexao, id_loja, {"ativa": False})


def listar_usuarios(conexao, *, limit: int, offset: int) -> list[dict[str, object]]:
    return _listar(
        conexao,
        """
        SELECT
            u.*,
            t.codigo AS tipo_usuario_codigo,
            t.nome AS tipo_usuario,
            l.nome AS loja
        FROM usuario u
        JOIN tipo_usuario t ON t.id_tipo_usuario = u.id_tipo_usuario
        LEFT JOIN loja l ON l.id_loja = u.id_loja
        ORDER BY u.nome
        LIMIT %s OFFSET %s
        """,
        (limit, offset),
    )


def obter_usuario(conexao, id_usuario: object) -> dict[str, object]:
    return _obter_por_id(conexao, "usuario", "id_usuario", id_usuario, "Usuario")


def criar_usuario(conexao, dados: dict[str, object]) -> dict[str, object]:
    return _criar(conexao, "usuario", dados)


def atualizar_usuario(conexao, id_usuario: object, dados: dict[str, object]) -> dict[str, object]:
    return _atualizar(
        conexao,
        "usuario",
        "id_usuario",
        id_usuario,
        dados,
        "Usuario",
        coluna_data="atualizado_em",
    )


def desativar_usuario(conexao, id_usuario: object) -> dict[str, object]:
    return atualizar_usuario(conexao, id_usuario, {"ativo": False})


def listar_produtos(conexao, *, limit: int, offset: int) -> list[dict[str, object]]:
    return _listar(
        conexao,
        """
        SELECT *
        FROM produto
        ORDER BY nome, marca
        LIMIT %s OFFSET %s
        """,
        (limit, offset),
    )


def obter_produto(conexao, id_produto: object) -> dict[str, object]:
    return _obter_por_id(conexao, "produto", "id_produto", id_produto, "Produto")


def criar_produto(conexao, dados: dict[str, object]) -> dict[str, object]:
    return _criar(conexao, "produto", dados)


def atualizar_produto(conexao, id_produto: object, dados: dict[str, object]) -> dict[str, object]:
    return _atualizar(
        conexao,
        "produto",
        "id_produto",
        id_produto,
        dados,
        "Produto",
        coluna_data="atualizado_em",
    )


def desativar_produto(conexao, id_produto: object) -> dict[str, object]:
    return atualizar_produto(conexao, id_produto, {"ativo": False})


def listar_variacoes(conexao, *, limit: int, offset: int) -> list[dict[str, object]]:
    return _listar(
        conexao,
        """
        SELECT
            v.*,
            p.nome AS produto,
            p.marca AS marca
        FROM variacao_produto v
        JOIN produto p ON p.id_produto = v.id_produto
        ORDER BY p.nome, v.cor, v.tamanho
        LIMIT %s OFFSET %s
        """,
        (limit, offset),
    )


def obter_variacao(conexao, id_variacao: object) -> dict[str, object]:
    return _obter_por_id(conexao, "variacao_produto", "id_variacao", id_variacao, "Variacao")


def criar_variacao(conexao, dados: dict[str, object]) -> dict[str, object]:
    return _criar(conexao, "variacao_produto", dados)


def atualizar_variacao(conexao, id_variacao: object, dados: dict[str, object]) -> dict[str, object]:
    return _atualizar(
        conexao,
        "variacao_produto",
        "id_variacao",
        id_variacao,
        dados,
        "Variacao",
        coluna_data="atualizada_em",
    )


def desativar_variacao(conexao, id_variacao: object) -> dict[str, object]:
    return atualizar_variacao(conexao, id_variacao, {"ativa": False})


def listar_opcoes(conexao, tabela: str, *, limit: int, offset: int) -> list[dict[str, object]]:
    return _listar(
        conexao,
        f"""
        SELECT *
        FROM {tabela}
        ORDER BY ordem, nome
        LIMIT %s OFFSET %s
        """,
        (limit, offset),
    )


def obter_opcao(conexao, tabela: str, coluna_id: str, id_registro: object, recurso: str):
    return _obter_por_id(conexao, tabela, coluna_id, id_registro, recurso)


def criar_opcao(conexao, tabela: str, dados: dict[str, object]) -> dict[str, object]:
    return _criar(conexao, tabela, dados)


def atualizar_opcao(
    conexao,
    tabela: str,
    coluna_id: str,
    id_registro: object,
    dados: dict[str, object],
    recurso: str,
) -> dict[str, object]:
    return _atualizar(conexao, tabela, coluna_id, id_registro, dados, recurso)


def desativar_opcao(
    conexao,
    tabela: str,
    coluna_id: str,
    id_registro: object,
    recurso: str,
) -> dict[str, object]:
    return atualizar_opcao(conexao, tabela, coluna_id, id_registro, {"ativo": False}, recurso)
