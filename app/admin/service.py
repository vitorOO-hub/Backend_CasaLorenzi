"""Regras simples do modulo administrativo."""

from app.admin import repositorio
from app.admin.erros import RegistroAdminNaoEncontrado
from app.core.repositorio import limpar_nulos, normalizar_id, normalizar_ids_no_dicionario

TABELAS_OPCOES = {
    "tipos-usuario": ("tipo_usuario", "id_tipo_usuario", "Tipo de usuario", True),
    "status-pedido": ("status_pedido", "id_status_pedido", "Status de pedido", True),
    "metodos-pagamento": ("metodo_pagamento", "id_metodo_pagamento", "Metodo de pagamento", False),
    "status-pagamento": ("status_pagamento", "id_status_pagamento", "Status de pagamento", False),
    "tipos-movimentacao-estoque": (
        "tipo_movimentacao_estoque",
        "id_tipo_movimentacao_estoque",
        "Tipo de movimentacao de estoque",
        False,
    ),
}


def preparar_dados(dados: dict[str, object]) -> dict[str, object]:
    return normalizar_ids_no_dicionario(limpar_nulos(dados))


def garantir_dados(dados: dict[str, object]) -> dict[str, object]:
    dados = preparar_dados(dados)
    if not dados:
        raise ValueError("Informe ao menos um campo para atualizar")
    return dados


def listar_lojas(conexao, *, limit: int, offset: int):
    return repositorio.listar_lojas(conexao, limit=limit, offset=offset)


def obter_loja(conexao, id_loja: str):
    return repositorio.obter_loja(conexao, normalizar_id(id_loja))


def criar_loja(conexao, dados: dict[str, object]):
    return repositorio.criar_loja(conexao, preparar_dados(dados))


def atualizar_loja(conexao, id_loja: str, dados: dict[str, object]):
    return repositorio.atualizar_loja(conexao, normalizar_id(id_loja), garantir_dados(dados))


def desativar_loja(conexao, id_loja: str):
    return repositorio.desativar_loja(conexao, normalizar_id(id_loja))


def listar_usuarios(conexao, *, limit: int, offset: int):
    return repositorio.listar_usuarios(conexao, limit=limit, offset=offset)


def obter_usuario(conexao, id_usuario: str):
    return repositorio.obter_usuario(conexao, normalizar_id(id_usuario))


def criar_usuario(conexao, dados: dict[str, object]):
    return repositorio.criar_usuario(conexao, preparar_dados(dados))


def atualizar_usuario(conexao, id_usuario: str, dados: dict[str, object]):
    return repositorio.atualizar_usuario(conexao, normalizar_id(id_usuario), garantir_dados(dados))


def desativar_usuario(conexao, id_usuario: str):
    return repositorio.desativar_usuario(conexao, normalizar_id(id_usuario))


def listar_produtos(conexao, *, limit: int, offset: int):
    return repositorio.listar_produtos(conexao, limit=limit, offset=offset)


def obter_produto(conexao, id_produto: str):
    return repositorio.obter_produto(conexao, normalizar_id(id_produto))


def criar_produto(conexao, dados: dict[str, object]):
    return repositorio.criar_produto(conexao, preparar_dados(dados))


def atualizar_produto(conexao, id_produto: str, dados: dict[str, object]):
    return repositorio.atualizar_produto(conexao, normalizar_id(id_produto), garantir_dados(dados))


def desativar_produto(conexao, id_produto: str):
    return repositorio.desativar_produto(conexao, normalizar_id(id_produto))


def listar_variacoes(conexao, *, limit: int, offset: int):
    return repositorio.listar_variacoes(conexao, limit=limit, offset=offset)


def obter_variacao(conexao, id_variacao: str):
    return repositorio.obter_variacao(conexao, normalizar_id(id_variacao))


def criar_variacao(conexao, dados: dict[str, object]):
    return repositorio.criar_variacao(conexao, preparar_dados(dados))


def atualizar_variacao(conexao, id_variacao: str, dados: dict[str, object]):
    return repositorio.atualizar_variacao(conexao, normalizar_id(id_variacao), garantir_dados(dados))


def desativar_variacao(conexao, id_variacao: str):
    return repositorio.desativar_variacao(conexao, normalizar_id(id_variacao))


def metadados_opcao(nome: str) -> tuple[str, str, str, bool]:
    try:
        return TABELAS_OPCOES[nome]
    except KeyError as erro:
        raise RegistroAdminNaoEncontrado("Opcao") from erro


def listar_opcoes(conexao, nome: str, *, limit: int, offset: int):
    tabela, _coluna_id, _recurso, _tem_descricao = metadados_opcao(nome)
    return repositorio.listar_opcoes(conexao, tabela, limit=limit, offset=offset)


def obter_opcao(conexao, nome: str, id_registro: str):
    tabela, coluna_id, recurso, _tem_descricao = metadados_opcao(nome)
    return repositorio.obter_opcao(conexao, tabela, coluna_id, normalizar_id(id_registro), recurso)


def criar_opcao(conexao, nome: str, dados: dict[str, object]):
    tabela, _coluna_id, _recurso, _tem_descricao = metadados_opcao(nome)
    return repositorio.criar_opcao(conexao, tabela, preparar_dados(dados))


def atualizar_opcao(conexao, nome: str, id_registro: str, dados: dict[str, object]):
    tabela, coluna_id, recurso, _tem_descricao = metadados_opcao(nome)
    return repositorio.atualizar_opcao(
        conexao,
        tabela,
        coluna_id,
        normalizar_id(id_registro),
        garantir_dados(dados),
        recurso,
    )


def desativar_opcao(conexao, nome: str, id_registro: str):
    tabela, coluna_id, recurso, _tem_descricao = metadados_opcao(nome)
    return repositorio.desativar_opcao(conexao, tabela, coluna_id, normalizar_id(id_registro), recurso)
