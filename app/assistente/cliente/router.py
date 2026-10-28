"""Rotas do assistente do cliente. O cliente vem sempre do JWT; o modelo nao concede permissao."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.assistente.cliente import service
from app.assistente.cliente.provedor import criar_provedor
from app.assistente.cliente.schemas import Conversa, MensagemCriacao, RespostaAssistente
from app.core.config import Settings, get_settings
from app.core.db import ExecutarDep
from app.core.papeis import UsuarioAtual
from app.core.security import get_current_user

# Prefixo proprio: /assistente/conversas e do chatbot administrativo (app.assistente.router).
router = APIRouter(prefix="/assistente/cliente", tags=["assistente-cliente"])

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
def iniciar_conversa(usuario: UsuarioDep, executar: ExecutarDep):
    return executar(lambda conexao: service.iniciar_conversa(conexao, usuario))


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
