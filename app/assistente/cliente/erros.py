"""Erros de negocio do assistente. O tratador unico (app.core.erros) gera a resposta."""

from fastapi import status

from app.core.erros import ErroDeNegocio


class ConversaNaoEncontrada(ErroDeNegocio):
    """Tambem cobre a conversa de outra pessoa: nao revela que ela existe."""

    status_code = status.HTTP_404_NOT_FOUND
    detalhe = "Conversa não encontrada"


class ConversaComAtendente(ErroDeNegocio):
    status_code = status.HTTP_409_CONFLICT
    detalhe = "Esta conversa foi passada para a nossa equipe; continue com o atendente."


class LimiteDiarioDoAssistente(ErroDeNegocio):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    detalhe = "Você atingiu o limite de mensagens do assistente por hoje. Tente de novo amanhã."


class ConversaArquivada(ErroDeNegocio):
    status_code = status.HTTP_409_CONFLICT
    detalhe = "Esta conversa foi arquivada. Comece um novo chat."


class RespostaNaoEncontrada(ErroDeNegocio):
    status_code = status.HTTP_404_NOT_FOUND
    detalhe = "Resposta não encontrada"
