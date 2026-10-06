"""Regras transacionais simples do modulo de compras."""

from app.compras import repositorio
from app.core.repositorio import limpar_nulos, normalizar_id, normalizar_ids_no_dicionario


def preparar_dados(dados: dict[str, object]) -> dict[str, object]:
    return normalizar_ids_no_dicionario(limpar_nulos(dados))


def garantir_dados(dados: dict[str, object]) -> dict[str, object]:
    dados = preparar_dados(dados)
    if not dados:
        raise ValueError("Informe ao menos um campo para atualizar")
    return dados


def listar_pedidos(conexao, *, limit: int, offset: int):
    return repositorio.listar_pedidos(conexao, limit=limit, offset=offset)


def obter_pedido(conexao, id_pedido: str):
    return repositorio.obter_pedido(conexao, normalizar_id(id_pedido))


def criar_pedido(conexao, dados: dict[str, object]):
    return repositorio.criar_pedido(conexao, preparar_dados(dados))


def atualizar_pedido(conexao, id_pedido: str, dados: dict[str, object]):
    return repositorio.atualizar_pedido(conexao, normalizar_id(id_pedido), garantir_dados(dados))


def atualizar_status_pedido(conexao, id_pedido: str, id_status_pedido: str | int):
    return repositorio.atualizar_pedido(
        conexao,
        normalizar_id(id_pedido),
        {"id_status_pedido": normalizar_id(id_status_pedido)},
    )


def cancelar_pedido(conexao, id_pedido: str):
    return repositorio.cancelar_pedido(conexao, normalizar_id(id_pedido))


def listar_itens_pedido(conexao, id_pedido: str):
    return repositorio.listar_itens_pedido(conexao, normalizar_id(id_pedido))


def obter_item_pedido(conexao, id_item_pedido: str):
    return repositorio.obter_item_pedido(conexao, normalizar_id(id_item_pedido))


def criar_item_pedido(conexao, id_pedido: str, dados: dict[str, object]):
    return repositorio.criar_item_pedido(conexao, normalizar_id(id_pedido), preparar_dados(dados))


def atualizar_item_pedido(conexao, id_item_pedido: str, dados: dict[str, object]):
    return repositorio.atualizar_item_pedido(
        conexao,
        normalizar_id(id_item_pedido),
        garantir_dados(dados),
    )


def remover_item_pedido(conexao, id_item_pedido: str):
    return repositorio.remover_item_pedido(conexao, normalizar_id(id_item_pedido))


def listar_pagamentos_pedido(conexao, id_pedido: str):
    return repositorio.listar_pagamentos_pedido(conexao, normalizar_id(id_pedido))


def obter_pagamento(conexao, id_pagamento: str):
    return repositorio.obter_pagamento(conexao, normalizar_id(id_pagamento))


def criar_pagamento(conexao, id_pedido: str, dados: dict[str, object]):
    return repositorio.criar_pagamento(conexao, normalizar_id(id_pedido), preparar_dados(dados))


def atualizar_status_pagamento(conexao, id_pagamento: str, dados: dict[str, object]):
    return repositorio.atualizar_status_pagamento(
        conexao,
        normalizar_id(id_pagamento),
        garantir_dados(dados),
    )
