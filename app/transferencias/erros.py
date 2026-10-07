"""Erros de negocio do modulo de transferencias de estoque."""

from fastapi import status

from app.core.erros import ErroDeNegocio


class TransferenciaNaoEncontrada(ErroDeNegocio):
    """Transferencia solicitada nao existe."""

    status_code = status.HTTP_404_NOT_FOUND
    detalhe = "Transferencia de estoque nao encontrada"


class OperadorSemLoja(ErroDeNegocio):
    """Operador precisa estar associado a uma loja para solicitar transferencia."""

    status_code = status.HTTP_409_CONFLICT
    detalhe = "Operador de estoque precisa estar vinculado a uma loja"


class TransferenciaInvalida(ErroDeNegocio):
    """Dados de transferencia nao obedecem ao fluxo permitido."""

    status_code = status.HTTP_409_CONFLICT
    detalhe = "Transferencia de estoque invalida para os dados informados"


class TransferenciaJaProcessada(ErroDeNegocio):
    """Transferencia ja saiu do status inicial."""

    status_code = status.HTTP_409_CONFLICT
    detalhe = "Transferencia de estoque ja foi processada"
