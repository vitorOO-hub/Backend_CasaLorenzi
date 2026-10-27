"""Rotas da area de clientes do painel (atendente, gerente e admin).

Rotas privadas: sempre exigem token valido e um destes papeis, independente de
AUTENTICACAO_OBRIGATORIA. O escopo de loja vem do token, nunca da requisicao.
"""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.clientes import service
from app.clientes.schemas import FichaCliente, ListaClientes, OpcoesClientes, VultoMaisDaFicha
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
    categoria: Literal["black", "ouro", "prata", "bronze", "sem_pontos"] | None = None,
    id_loja_cadastro: Annotated[UUID | None, Query(description="Loja de cadastro")] = None,
    marca: Literal["casa_lorenzi", "vulto"] | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    def operacao(conexao):
        escopo = service.montar_escopo(conexao, usuario, id_loja)
        return service.listar(
            conexao,
            usuario,
            escopo,
            busca=busca,
            secao=secao,
            limit=limit,
            offset=offset,
            categoria=categoria,
            id_loja_cadastro=id_loja_cadastro,
            marca=marca,
        )

    return executar(operacao)


# Antes de "/{id_cliente}": senao "opcoes" seria lido como um id.
@router.get("/opcoes", response_model=OpcoesClientes, summary="Opcoes dos filtros da lista")
def opcoes(usuario: UsuarioDep, executar: ExecutarDep):
    return executar(service.opcoes)


@router.get("/{id_cliente}", response_model=FichaCliente, summary="Ficha do cliente")
def ficha(id_cliente: UUID, usuario: UsuarioDep, executar: ExecutarDep, id_loja: IdLoja = None):
    def operacao(conexao):
        escopo = service.montar_escopo(conexao, usuario, id_loja)
        return service.ficha(conexao, usuario, escopo, id_cliente)

    return executar(operacao)


@router.get(
    "/{id_cliente}/vulto-mais", response_model=VultoMaisDaFicha, summary="Pontos Vulto+ do cliente"
)
def vulto_mais(
    id_cliente: UUID, usuario: UsuarioDep, executar: ExecutarDep, id_loja: IdLoja = None
):
    def operacao(conexao):
        escopo = service.montar_escopo(conexao, usuario, id_loja)
        resposta = service.vulto_mais(conexao, usuario, escopo, id_cliente)
        conexao.commit()  # grava os vencimentos lancados na leitura
        return resposta

    return executar(operacao)
