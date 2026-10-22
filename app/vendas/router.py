"""Rotas das vendas em loja (`/api/v1/painel/vendas`): so o vendedor.

O vendedor ve todas as vendas e todos os clientes cadastrados, e lanca vendas para um CPF. A loja
da venda e a pessoa que vende vem do token, nunca do corpo.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query

from app.core.db import ExecutarDep
from app.core.papeis import UsuarioAtual
from app.core.security import requer_papel
from app.vendas import service
from app.vendas.schemas import (
    BuscaDeCliente,
    ClienteDaVenda,
    DetalheDaVenda,
    ListaDeClientes,
    ListaDeVendas,
    NovaVenda,
    OpcoesDeVenda,
    PecaNoEstoque,
)

router = APIRouter(prefix="/painel/vendas", tags=["painel-vendas"])

UsuarioDep = Annotated[UsuarioAtual, Depends(requer_papel(*service.PAPEIS_DE_VENDA))]
Busca = Annotated[str | None, Query(max_length=80, description="Nome, numero, e-mail ou CPF")]
ChaveIdempotencia = Annotated[str | None, Header(alias="Idempotency-Key", max_length=160)]


@router.get("", response_model=ListaDeVendas, summary="Todas as vendas registradas")
def listar(
    usuario: UsuarioDep,
    executar: ExecutarDep,
    busca: Busca = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return executar(lambda c: service.listar_vendas(c, busca, limit=limit, offset=offset))


@router.post("", response_model=DetalheDaVenda, summary="Lancar venda em loja para um CPF")
def lancar(
    dados: NovaVenda,
    usuario: UsuarioDep,
    executar: ExecutarDep,
    chave: ChaveIdempotencia = None,
):
    corpo = dados.model_dump()
    return executar(lambda c: service.lancar_venda(c, usuario, corpo, chave_idempotencia=chave))


@router.get("/opcoes", response_model=OpcoesDeVenda, summary="Formas de pagamento e loja")
def opcoes(usuario: UsuarioDep, executar: ExecutarDep):
    return executar(lambda c: service.opcoes(c, usuario))


@router.get(
    "/pecas", response_model=list[PecaNoEstoque], summary="Pecas com saldo na loja do vendedor"
)
def pecas(
    usuario: UsuarioDep,
    executar: ExecutarDep,
    busca: Busca = None,
    limit: int = Query(default=20, ge=1, le=50),
):
    return executar(lambda c: service.pecas(c, usuario, busca, limit=limit))


@router.get("/clientes", response_model=ListaDeClientes, summary="Todos os clientes cadastrados")
def clientes(
    usuario: UsuarioDep,
    executar: ExecutarDep,
    busca: Busca = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return executar(lambda c: service.listar_clientes(c, busca, limit=limit, offset=offset))


@router.post("/clientes/buscar", response_model=ClienteDaVenda, summary="Achar o cliente pelo CPF")
def buscar_cliente(dados: BuscaDeCliente, usuario: UsuarioDep, executar: ExecutarDep):
    return executar(lambda c: service.buscar_cliente(c, dados.cpf))


@router.get("/{id_pedido}", response_model=DetalheDaVenda, summary="Detalhe de uma venda")
def detalhe(id_pedido: UUID, usuario: UsuarioDep, executar: ExecutarDep):
    return executar(lambda c: service.obter_venda(c, id_pedido))
