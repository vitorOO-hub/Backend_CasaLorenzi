"""Erros de negocio do chat ao vivo. O tratador unico (app.core.erros) gera a resposta."""

from fastapi import status

from app.core.erros import ErroDeNegocio


class MensagemDeReferenciaInexistente(ErroDeNegocio):
    """O cursor `apos` aponta para uma mensagem que nao existe nesta conversa."""

    status_code = status.HTTP_404_NOT_FOUND
    detalhe = "Mensagem de referencia nao encontrada nesta conversa"
