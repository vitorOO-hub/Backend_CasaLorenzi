"""Rotas da area de clientes do painel (atendente, gerente e admin).

Rotas privadas: sempre exigem token valido e um destes papeis, independente de
AUTENTICACAO_OBRIGATORIA. O escopo de loja vem do token, nunca da requisicao.
"""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.clientes import service
from app.clientes.schemas import FichaCliente, ListaClientes
from app.core.db import ExecutarDep
from app.core.papeis import UsuarioAtual
from app.core.security import requer_papel

router = APIRouter(prefix="/painel/clientes", tags=["painel-clientes"])

UsuarioDep = Annotated[UsuarioAtual, Depends(requer_papel(*service.PAPEIS_DO_PAINEL))]
IdLoja = Annotated[UUID | None, Query(description="So o admin escolhe a loja")]


@router.get("", response_model=ListaClientes, summary="Lista de clientes")
def listar(
    usuario: UsuarioDep,
    executar: ExecutarDep,
    busca: Annotated[
        str | None, Query(max_length=80, description="Nome, e-mail ou telefone")
    ] = None,
    secao: Literal["todos", "com_aberto", "meus"] = "todos",
    id_loja: IdLoja = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    def operacao(conexao):
        escopo = service.montar_escopo(conexao, usuario, id_loja)
        return service.listar(
            conexao, usuario, escopo, busca=busca, secao=secao, limit=limit, offset=offset
        )

    return executar(operacao)


@router.get("/{id_cliente}", response_model=FichaCliente, summary="Ficha do cliente")
def ficha(id_cliente: UUID, usuario: UsuarioDep, executar: ExecutarDep, id_loja: IdLoja = None):
    def operacao(conexao):
        escopo = service.montar_escopo(conexao, usuario, id_loja)
        return service.ficha(conexao, usuario, escopo, id_cliente)

    return executar(operacao)
