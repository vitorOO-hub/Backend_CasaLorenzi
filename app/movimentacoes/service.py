"""Regras simples para movimentacoes de estoque."""

from app.core.repositorio import limpar_nulos, normalizar_id, normalizar_ids_no_dicionario
from app.movimentacoes import repositorio


def preparar_dados(dados: dict[str, object]) -> dict[str, object]:
    return normalizar_ids_no_dicionario(limpar_nulos(dados))


def listar_movimentacoes(conexao, *, limit: int, offset: int):
    return repositorio.listar_movimentacoes(conexao, limit=limit, offset=offset)


def obter_movimentacao(conexao, id_movimentacao: str):
    return repositorio.obter_movimentacao(conexao, normalizar_id(id_movimentacao))


def criar_movimentacao(conexao, dados: dict[str, object]):
    return repositorio.criar_movimentacao(conexao, preparar_dados(dados))
