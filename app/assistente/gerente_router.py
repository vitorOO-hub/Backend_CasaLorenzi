"""Rotas do chatbot do gerente: somente gerente autenticado e consultas de leitura."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.assistente import gerente, repositorio, service
from app.assistente.provedor import FalhaDoProvedor
from app.assistente.schemas import (
    Conversa,
    HistoricoConversa,
    Mensagem,
    NovaConversa,
    RespostaAssistente,
)
from app.core.config import Settings, get_settings
from app.core.db import ExecutarDep
from app.core.papeis import Papel, UsuarioAtual
from app.core.security import requer_papel

router = APIRouter(prefix="/assistente/gerente", tags=["assistente-gerente"])
GerenteDep = Annotated[UsuarioAtual, Depends(requer_papel(Papel.GERENTE_LOJA))]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def _traduzir_erro(erro: Exception) -> None:
    if isinstance(erro, (repositorio.ConversaNaoEncontrada, service.AcessoNegado)):
        raise HTTPException(status_code=404, detail="Conversa não encontrada") from erro
    if isinstance(erro, repositorio.LimiteDiarioAtingido):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Limite diário do assistente atingido. Tente novamente amanhã.",
        ) from erro
    raise erro


@router.post("/conversas", response_model=Conversa, status_code=status.HTTP_201_CREATED)
def criar_conversa(dados: NovaConversa, usuario: GerenteDep, executar: ExecutarDep):
    try:
        return executar(lambda c: gerente.criar_conversa(c, usuario, dados.titulo))
    except (service.AcessoNegado, repositorio.ConversaNaoEncontrada) as erro:
        _traduzir_erro(erro)


@router.get("/conversas", response_model=list[Conversa])
def listar_conversas(usuario: GerenteDep, executar: ExecutarDep):
    try:
        return executar(lambda c: gerente.listar_conversas(c, usuario))
    except service.AcessoNegado as erro:
        _traduzir_erro(erro)


@router.get("/conversas/{id_conversa}", response_model=HistoricoConversa)
def obter_conversa(id_conversa: UUID, usuario: GerenteDep, executar: ExecutarDep):
    try:
        return executar(lambda c: gerente.obter_conversa(c, usuario, id_conversa))
    except (service.AcessoNegado, repositorio.ConversaNaoEncontrada) as erro:
        _traduzir_erro(erro)


@router.post("/conversas/{id_conversa}/mensagens", response_model=RespostaAssistente)
def enviar_mensagem(
    id_conversa: UUID,
    dados: Mensagem,
    usuario: GerenteDep,
    executar: ExecutarDep,
    configuracoes: SettingsDep,
):
    try:
        return gerente.enviar_mensagem(
            executar, usuario, configuracoes, id_conversa, dados.texto
        )
    except (
        service.AcessoNegado,
        repositorio.ConversaNaoEncontrada,
        repositorio.LimiteDiarioAtingido,
    ) as erro:
        _traduzir_erro(erro)
    except FalhaDoProvedor as erro:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=service.mensagem_sem_confirmacao(
                dados.texto,
                "o provedor de IA ficou indisponível antes de validar os dados.",
            ),
        ) from erro
