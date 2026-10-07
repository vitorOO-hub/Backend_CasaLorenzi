"""Regras do fluxo de transferencias e reposicoes de estoque."""

from app.core.repositorio import normalizar_id
from app.transferencias import repositorio
from app.transferencias.erros import OperadorSemLoja


def _loja_do_operador(id_loja: object | None):
    if not id_loja:
        raise OperadorSemLoja
    return normalizar_id(id_loja)


def listar_transferencias(
    conexao,
    *,
    id_loja_operador: str | None,
    recebidas: bool,
    limit: int,
    offset: int,
):
    return repositorio.listar_transferencias(
        conexao,
        id_loja=_loja_do_operador(id_loja_operador),
        recebidas=recebidas,
        limit=limit,
        offset=offset,
    )


def obter_transferencia(conexao, id_transferencia: str):
    return repositorio.obter_transferencia(conexao, normalizar_id(id_transferencia))


def solicitar_transferencia(
    conexao,
    *,
    id_loja_operador: object | None,
    auth_user_id_solicitante: object,
    dados: dict[str, object],
):
    return repositorio.solicitar_transferencia(
        conexao,
        id_loja_origem=normalizar_id(dados["id_loja_origem"]),
        id_loja_destino=_loja_do_operador(id_loja_operador),
        id_variacao=normalizar_id(dados["id_variacao"]),
        auth_user_id_solicitante=normalizar_id(auth_user_id_solicitante),
        quantidade=int(dados["quantidade"]),
        observacao=dados.get("observacao"),
    )


def solicitar_reposicao(
    conexao,
    *,
    id_loja_operador: object | None,
    auth_user_id_solicitante: object,
    dados: dict[str, object],
):
    return repositorio.solicitar_reposicao(
        conexao,
        id_loja_destino=_loja_do_operador(id_loja_operador),
        id_variacao=normalizar_id(dados["id_variacao"]),
        auth_user_id_solicitante=normalizar_id(auth_user_id_solicitante),
        quantidade=int(dados["quantidade"]),
        observacao=dados.get("observacao"),
    )


def aceitar_transferencia(
    conexao,
    *,
    id_transferencia: str,
    id_loja_operador: object | None,
    auth_user_id_responsavel: object,
):
    return repositorio.aceitar_transferencia(
        conexao,
        id_transferencia=normalizar_id(id_transferencia),
        id_loja_responsavel=_loja_do_operador(id_loja_operador),
        auth_user_id_responsavel=normalizar_id(auth_user_id_responsavel),
    )
