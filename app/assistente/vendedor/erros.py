"""Erros de negocio do chat do assistente. O tratador unico (app.core.erros) gera a resposta."""

from fastapi import status

from app.core.erros import ErroDeNegocio


class ConversaNaoEncontrada(ErroDeNegocio):
    """Tambem cobre conversa de outra pessoa: nao revela que ela existe."""

    status_code = status.HTTP_404_NOT_FOUND
    detalhe = "Conversa nao encontrada"


class ConversaArquivada(ErroDeNegocio):
    status_code = status.HTTP_409_CONFLICT
    detalhe = "Esta conversa foi arquivada. Desarquive ou comece um novo chat."


class PerguntasDemaisPorMinuto(ErroDeNegocio):
    """Limite por pessoa (no banco, vale para todas as instancias do servidor)."""

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    detalhe = "Muitas perguntas em pouco tempo. Aguarde um minuto e tente de novo."


class LimiteDiarioDoAssistente(ErroDeNegocio):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    detalhe = "Voce chegou ao limite de perguntas ao assistente por hoje. Tente amanha."
