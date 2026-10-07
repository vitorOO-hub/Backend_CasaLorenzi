"""Rotas da area de chamados do painel (atendente, gerente e admin).

Sempre exigem token valido e um destes papeis, independente de AUTENTICACAO_OBRIGATORIA. O
remetente, o papel e a loja nunca vem do corpo: vem do token.
"""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.chamados import service
from app.chamados.schemas import (
    DetalheChamado,
    ItemChamado,
    ListaChamados,
    MensagemChamado,
    MensagemCriar,
    OpcoesChamados,
    ResumoChamados,
)
from app.core.db import ExecutarDep
from app.core.papeis import UsuarioAtual
from app.core.security import requer_papel

router = APIRouter(prefix="/painel/atendimentos", tags=["painel-atendimentos"])

UsuarioDep = Annotated[UsuarioAtual, Depends(requer_papel(*service.PAPEIS_DO_PAINEL))]
Codigo = Annotated[str | None, Query(max_length=40, pattern=r"^[a-z0-9_]+$")]
IdLoja = Annotated[UUID | None, Query(description="So o admin escolhe a loja")]


@router.get("/opcoes", response_model=OpcoesChamados, summary="Opcoes dos filtros")
def opcoes(usuario: UsuarioDep, executar: ExecutarDep, id_loja: IdLoja = None):
    def operacao(conexao):
        escopo = service.montar_escopo(conexao, usuario, id_loja)
        return service.opcoes(conexao, usuario, escopo)

    return executar(operacao)


@router.get("/resumo", response_model=ResumoChamados, summary="Contadores dos cartoes")
def resumo(usuario: UsuarioDep, executar: ExecutarDep, id_loja: IdLoja = None):
    def operacao(conexao):
        return service.resumo(conexao, service.montar_escopo(conexao, usuario, id_loja))

    return executar(operacao)


@router.get("", response_model=ListaChamados, summary="Lista de chamados")
def listar(
    usuario: UsuarioDep,
    executar: ExecutarDep,
    situacao: Literal["abertos", "aberto", "em_andamento", "resolvido", "todos"] = "abertos",
    responsavel: Literal["todos", "eu", "fila"] = "todos",
    prioridade: Literal["baixa", "media", "alta", "urgente"] | None = None,
    canal: Codigo = None,
    categoria: Codigo = None,
    id_loja: IdLoja = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    def operacao(conexao):
        escopo = service.montar_escopo(conexao, usuario, id_loja)
        return service.listar(
            conexao,
            escopo,
            situacao=situacao,
            responsavel=responsavel,
            prioridade=prioridade,
            canal=canal,
            categoria=categoria,
            limit=limit,
            offset=offset,
        )

    return executar(operacao)


@router.get("/{id_atendimento}", response_model=DetalheChamado, summary="Detalhe do chamado")
def detalhe(id_atendimento: UUID, usuario: UsuarioDep, executar: ExecutarDep):
    def operacao(conexao):
        escopo = service.montar_escopo(conexao, usuario, None)
        return service.detalhe(conexao, usuario, escopo, id_atendimento)

    return executar(operacao)


@router.get(
    "/{id_atendimento}/mensagens",
    response_model=list[MensagemChamado],
    summary="Conversa do chamado",
)
def listar_mensagens(id_atendimento: UUID, usuario: UsuarioDep, executar: ExecutarDep):
    def operacao(conexao):
        escopo = service.montar_escopo(conexao, usuario, None)
        return service.mensagens(conexao, escopo, id_atendimento)

    return executar(operacao)


@router.post(
    "/{id_atendimento}/mensagens",
    response_model=MensagemChamado,
    status_code=status.HTTP_201_CREATED,
    summary="Responder ao cliente",
)
def enviar_mensagem(
    id_atendimento: UUID, dados: MensagemCriar, usuario: UsuarioDep, executar: ExecutarDep
):
    def operacao(conexao):
        escopo = service.montar_escopo(conexao, usuario, None)
        return service.enviar_mensagem(conexao, usuario, escopo, id_atendimento, dados.texto)

    return executar(operacao)


@router.post("/{id_atendimento}/assumir", response_model=ItemChamado, summary="Assumir o chamado")
def assumir(id_atendimento: UUID, usuario: UsuarioDep, executar: ExecutarDep):
    def operacao(conexao):
        escopo = service.montar_escopo(conexao, usuario, None)
        return service.assumir(conexao, escopo, id_atendimento)

    return executar(operacao)


@router.post("/{id_atendimento}/resolver", response_model=ItemChamado, summary="Resolver o chamado")
def resolver(id_atendimento: UUID, usuario: UsuarioDep, executar: ExecutarDep):
    def operacao(conexao):
        escopo = service.montar_escopo(conexao, usuario, None)
        return service.resolver(conexao, usuario, escopo, id_atendimento)

    return executar(operacao)
