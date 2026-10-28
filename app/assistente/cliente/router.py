"""Rotas do assistente do cliente. O cliente vem sempre do JWT; o modelo nao concede permissao.

`router_visitante` e a unica rota publica: quem navega sem login so ve dados publicos do catalogo
(limite por minuto na borda e teto diario por IP em app/assistente/cliente/visitante.py).
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Request, status

from app.assistente.cliente import service, visitante
from app.assistente.cliente.provedor import criar_provedor
from app.assistente.cliente.schemas import (
    Conversa,
    MensagemCriacao,
    MensagemVisitante,
    NovaConversa,
    RespostaAssistente,
    RespostaVisitante,
)
from app.core.config import Settings, get_settings
from app.core.db import ExecutarDep
from app.core.papeis import UsuarioAtual
from app.core.protecoes import LimitadorDeRequisicoes
from app.core.security import get_current_user

# Prefixo proprio: /assistente/conversas e do chatbot administrativo (app.assistente.router).
router = APIRouter(prefix="/assistente/cliente", tags=["assistente-cliente"])
router_visitante = APIRouter(prefix="/assistente/visitante", tags=["assistente-cliente"])

UsuarioDep = Annotated[UsuarioAtual, Depends(get_current_user)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_fabrica_provedor() -> service.FabricaProvedor:
    """Separada para os testes trocarem o provedor real por um falso."""
    return criar_provedor


FabricaDep = Annotated[service.FabricaProvedor, Depends(get_fabrica_provedor)]


@router.post(
    "/conversas",
    response_model=Conversa,
    status_code=status.HTTP_201_CREATED,
    summary="Abre uma conversa com o assistente",
)
def iniciar_conversa(
    usuario: UsuarioDep,
    executar: ExecutarDep,
    dados: Annotated[NovaConversa | None, Body()] = None,
):
    historico = [m.model_dump() for m in dados.historico] if dados else []
    return executar(lambda conexao: service.iniciar_conversa(conexao, usuario, historico))


@router.get("/conversas/{id_conversa}", response_model=Conversa, summary="Conversa e mensagens")
def obter_conversa(id_conversa: UUID, usuario: UsuarioDep, executar: ExecutarDep):
    return executar(lambda conexao: service.obter_conversa(conexao, usuario, id_conversa))


@router.post(
    "/conversas/{id_conversa}/mensagens",
    response_model=RespostaAssistente,
    summary="Envia uma mensagem e recebe a resposta do assistente",
)
def enviar_mensagem(
    id_conversa: UUID,
    dados: MensagemCriacao,
    usuario: UsuarioDep,
    executar: ExecutarDep,
    configuracoes: SettingsDep,
    fabrica: FabricaDep,
):
    return executar(
        lambda conexao: service.enviar_mensagem(
            conexao, usuario, id_conversa, dados.texto, configuracoes=configuracoes, fabrica=fabrica
        )
    )


@router_visitante.post(
    "/mensagens",
    response_model=RespostaVisitante,
    summary="Publica: pergunta de quem navega sem login (so dados publicos do catalogo)",
)
def responder_visitante(
    dados: MensagemVisitante,
    request: Request,
    executar: ExecutarDep,
    configuracoes: SettingsDep,
    fabrica: FabricaDep,
):
    # Mesmo IP que o limite da borda usa (CF-Connecting-IP atras da Cloudflare).
    visitante.CONTADOR.registrar(LimitadorDeRequisicoes._ip(request.scope))
    historico = [m.model_dump() for m in dados.historico]
    return executar(
        lambda conexao: visitante.responder(
            conexao, dados.texto, historico, configuracoes=configuracoes, fabrica=fabrica
        )
    )
