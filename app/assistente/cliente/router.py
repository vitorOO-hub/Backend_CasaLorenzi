"""Rotas do assistente do cliente. O cliente vem sempre do JWT; o modelo nao concede permissao."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.assistente.cliente import service
from app.assistente.cliente.provedor import criar_provedor
from app.assistente.cliente.schemas import (
    AlteracaoDaConversa,
    AvaliacaoDaResposta,
    Conversa,
    ConversaResumo,
    MensagemCriacao,
    RespostaAssistente,
    SugestaoChamado,
    SugestaoChamadoEntrada,
)
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


@router.get("/conversas", response_model=list[ConversaResumo], summary="Historico de conversas")
def listar_conversas(usuario: UsuarioDep, executar: ExecutarDep):
    return executar(lambda conexao: service.listar_conversas(conexao, usuario))


@router.patch(
    "/conversas/{id_conversa}", response_model=Conversa, summary="Arquivar ou desarquivar"
)
def alterar_conversa(
    id_conversa: UUID, dados: AlteracaoDaConversa, usuario: UsuarioDep, executar: ExecutarDep
):
    return executar(
        lambda conexao: service.arquivar_conversa(conexao, usuario, id_conversa, dados.arquivada)
    )


@router.put(
    "/conversas/{id_conversa}/mensagens/{id_mensagem}/avaliacao",
    response_model=AvaliacaoDaResposta,
    summary="Avaliar uma resposta (util ou nao)",
)
def avaliar_resposta(
    id_conversa: UUID,
    id_mensagem: UUID,
    dados: AvaliacaoDaResposta,
    usuario: UsuarioDep,
    executar: ExecutarDep,
):
    executar(
        lambda conexao: service.avaliar_resposta(
            conexao, usuario, id_conversa, id_mensagem, dados.avaliacao
        )
    )
    return dados


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


@router.post(
    "/sugestao-chamado",
    response_model=SugestaoChamado,
    summary="Resposta rapida antes de abrir um chamado (ou nenhuma)",
)
def sugestao_chamado(
    dados: SugestaoChamadoEntrada,
    usuario: UsuarioDep,
    executar: ExecutarDep,
    configuracoes: SettingsDep,
    fabrica: FabricaDep,
):
    return executar(
        lambda conexao: service.sugerir_antes_do_chamado(
            conexao,
            usuario,
            dados.assunto,
            dados.descricao,
            configuracoes=configuracoes,
            fabrica=fabrica,
        )
    )
