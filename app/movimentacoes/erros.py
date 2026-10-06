"""Erros de negocio do modulo de movimentacoes."""

from fastapi import status

from app.core.erros import ErroDeNegocio


class MovimentacaoNaoEncontrada(ErroDeNegocio):
    status_code = status.HTTP_404_NOT_FOUND
    detalhe = "Movimentacao de estoque nao encontrada"


class MovimentacaoInvalida(ErroDeNegocio):
    status_code = status.HTTP_409_CONFLICT
    detalhe = "Movimentacao de estoque invalida para os dados informados"
