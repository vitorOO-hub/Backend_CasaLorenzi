"""Erros de negocio do assistente. O tratador unico (app.core.erros) gera a resposta."""

from fastapi import status

from app.core.erros import ErroDeNegocio


class ConversaNaoEncontrada(ErroDeNegocio):
    """Tambem cobre a conversa de outra pessoa: nao revela que ela existe."""

    status_code = status.HTTP_404_NOT_FOUND
    detalhe = "Conversa nao encontrada"


class ConversaComAtendente(ErroDeNegocio):
    status_code = status.HTTP_409_CONFLICT
    detalhe = "Esta conversa foi passada para um atendente; continue pelo atendimento"


class LimiteDiarioDoAssistente(ErroDeNegocio):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    detalhe = "Voce atingiu o limite de mensagens do assistente por hoje. Tente amanha."
