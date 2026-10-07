"""Rotas do chat ao vivo do painel (atendente, gerente e admin).

Rotas privadas: sempre exigem token valido e um destes papeis, independente de
AUTENTICACAO_OBRIGATORIA. Remetente, papel e loja vem do token, nunca do corpo.

O "ao vivo" e do Supabase Realtime, direto do front (as policies de RLS decidem o que cada pessoa
recebe). Estas rotas montam a tela e recuperam o que se perdeu se a conexao cair.
"""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.chamados.schemas import MensagemChamado, MensagemCriar
from app.chat import service
from app.chat.schemas import Lido, ListaConversas, MensagensChat, ResumoConversas, SessaoChat
from app.core.db import ExecutarDep
from app.core.papeis import UsuarioAtual
from app.core.security import requer_papel

router = APIRouter(prefix="/painel/chat", tags=["painel-chat"])

UsuarioDep = Annotated[UsuarioAtual, Depends(requer_papel(*service.PAPEIS_DO_PAINEL))]
IdLoja = Annotated[UUID | None, Query(description="So o admin escolhe a loja")]


@router.get("/conversas", response_model=ListaConversas, summary="Caixa de conversas")
def conversas(
    usuario: UsuarioDep,
    executar: ExecutarDep,
    secao: Literal["todas", "fila", "minhas"] = "todas",
    apenas_nao_lidas: bool = False,
    id_loja: IdLoja = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    def operacao(conexao):
        escopo = service.montar_escopo(conexao, usuario, id_loja)
        return service.listar(
            conexao,
            escopo,
            secao=secao,
            apenas_nao_lidas=apenas_nao_lidas,
            limit=limit,
            offset=offset,
        )

    return executar(operacao)


@router.get("/conversas/resumo", response_model=ResumoConversas, summary="Contadores da caixa")
def resumo(usuario: UsuarioDep, executar: ExecutarDep, id_loja: IdLoja = None):
    def operacao(conexao):
        return service.resumo(conexao, service.montar_escopo(conexao, usuario, id_loja))

    return executar(operacao)


@router.get(
    "/conversas/{id_atendimento}/sessao",
    response_model=SessaoChat,
    summary="Sessao do chat: canal, quem sou eu e se posso responder",
)
def sessao(id_atendimento: UUID, usuario: UsuarioDep, executar: ExecutarDep):
    def operacao(conexao):
        escopo = service.montar_escopo(conexao, usuario, None)
        return service.sessao(conexao, usuario, escopo, id_atendimento)

    return executar(operacao)


@router.get(
    "/conversas/{id_atendimento}/mensagens",
    response_model=MensagensChat,
    summary="Mensagens (as ultimas, ou so as novas depois de `apos`)",
)
def mensagens(
    id_atendimento: UUID,
    usuario: UsuarioDep,
    executar: ExecutarDep,
    apos: Annotated[
        UUID | None, Query(description="id da ultima mensagem que o front ja tem")
    ] = None,
    limit: int = Query(default=100, ge=1, le=200),
):
    def operacao(conexao):
        escopo = service.montar_escopo(conexao, usuario, None)
        return service.mensagens(conexao, escopo, id_atendimento, apos=apos, limit=limit)

    return executar(operacao)


@router.post(
    "/conversas/{id_atendimento}/mensagens",
    response_model=MensagemChamado,
    status_code=status.HTTP_201_CREATED,
    summary="Enviar mensagem",
)
def enviar_mensagem(
    id_atendimento: UUID, dados: MensagemCriar, usuario: UsuarioDep, executar: ExecutarDep
):
    def operacao(conexao):
        escopo = service.montar_escopo(conexao, usuario, None)
        return service.enviar_mensagem(conexao, usuario, escopo, id_atendimento, dados.texto)

    return executar(operacao)


@router.post(
    "/conversas/{id_atendimento}/lido", response_model=Lido, summary="Marcar a conversa como lida"
)
def marcar_lido(id_atendimento: UUID, usuario: UsuarioDep, executar: ExecutarDep):
    def operacao(conexao):
        escopo = service.montar_escopo(conexao, usuario, None)
        return service.marcar_lido(conexao, escopo, id_atendimento)

    return executar(operacao)
