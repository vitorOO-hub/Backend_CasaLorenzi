"""Rotas do fluxo de transferencia e reposicao de estoque."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.exc import IntegrityError

from app.core.db import ExecutarDep, eh_violacao_chave_estrangeira, eh_violacao_check
from app.core.papeis import Papel, UsuarioAtual
from app.core.security import requer_papel
from app.transferencias import service
from app.transferencias.erros import OperadorSemLoja, TransferenciaInvalida
from app.transferencias.schemas import (
    ReposicaoCriacao,
    TransferenciaCriacao,
    TransferenciaLeitura,
)

OperadorEstoque = Annotated[UsuarioAtual, Depends(requer_papel(Papel.OPERADOR_ESTOQUE))]

router = APIRouter(prefix="/transferencias-estoque", tags=["transferencias-estoque"])

Pagina = Query(default=20, ge=1, le=100)
Deslocamento = Query(default=0, ge=0)


def exigir_loja(usuario: UsuarioAtual):
    if not usuario.id_loja:
        raise OperadorSemLoja
    return usuario.id_loja


@router.get("", response_model=list[TransferenciaLeitura])
def listar(
    usuario: OperadorEstoque,
    executar: ExecutarDep,
    recebidas: bool = False,
    limit: int = Pagina,
    offset: int = Deslocamento,
):
    id_loja = exigir_loja(usuario)
    return executar(
        lambda conexao: service.listar_transferencias(
            conexao,
            id_loja_operador=id_loja,
            recebidas=recebidas,
            limit=limit,
            offset=offset,
        )
    )


@router.get("/{id_transferencia}", response_model=TransferenciaLeitura)
def obter(id_transferencia: str, _usuario: OperadorEstoque, executar: ExecutarDep):
    return executar(lambda conexao: service.obter_transferencia(conexao, id_transferencia))


@router.post("", status_code=status.HTTP_201_CREATED, response_model=TransferenciaLeitura)
def solicitar(
    dados: TransferenciaCriacao,
    usuario: OperadorEstoque,
    executar: ExecutarDep,
):
    id_loja = exigir_loja(usuario)
    try:
        return executar(
            lambda conexao: service.solicitar_transferencia(
                conexao,
                id_loja_operador=id_loja,
                auth_user_id_solicitante=usuario.id_auth,
                dados=dados.model_dump(),
            )
        )
    except IntegrityError as erro:
        if eh_violacao_chave_estrangeira(erro) or eh_violacao_check(erro):
            raise TransferenciaInvalida from erro
        raise


@router.post(
    "/reposicoes",
    status_code=status.HTTP_201_CREATED,
    response_model=TransferenciaLeitura,
)
def solicitar_reposicao(
    dados: ReposicaoCriacao,
    usuario: OperadorEstoque,
    executar: ExecutarDep,
):
    id_loja = exigir_loja(usuario)
    try:
        return executar(
            lambda conexao: service.solicitar_reposicao(
                conexao,
                id_loja_operador=id_loja,
                auth_user_id_solicitante=usuario.id_auth,
                dados=dados.model_dump(),
            )
        )
    except IntegrityError as erro:
        if eh_violacao_chave_estrangeira(erro) or eh_violacao_check(erro):
            raise TransferenciaInvalida from erro
        raise


@router.post("/{id_transferencia}/aceitar", response_model=TransferenciaLeitura)
def aceitar(id_transferencia: str, usuario: OperadorEstoque, executar: ExecutarDep):
    id_loja = exigir_loja(usuario)
    return executar(
        lambda conexao: service.aceitar_transferencia(
            conexao,
            id_transferencia=id_transferencia,
            id_loja_operador=id_loja,
            auth_user_id_responsavel=usuario.id_auth,
        )
    )
