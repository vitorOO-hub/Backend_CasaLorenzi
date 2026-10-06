"""Erros de negocio do modulo de estoque. O tratador unico (app.core.erros) gera a resposta."""

from fastapi import status

from app.core.erros import ErroDeNegocio


class RegistroNaoEncontrado(ErroDeNegocio):
    """Registro solicitado nao existe."""

    status_code = status.HTTP_404_NOT_FOUND
    detalhe = "Estoque nao encontrado"


class EstoqueInsuficiente(ErroDeNegocio):
    """Saida maior que o saldo disponivel."""

    status_code = status.HTTP_409_CONFLICT
    detalhe = "Estoque insuficiente para realizar a saida"


class EstoqueComSaldo(ErroDeNegocio):
    """Registro de estoque com saldo nao deve ser removido."""

    status_code = status.HTTP_409_CONFLICT
    detalhe = "Nao e possivel remover estoque com saldo maior que zero"


class EstoqueDuplicado(ErroDeNegocio):
    """Ja existe estoque para a combinacao de loja e variacao."""

    status_code = status.HTTP_409_CONFLICT
    detalhe = "Ja existe estoque para esta loja e variacao"
