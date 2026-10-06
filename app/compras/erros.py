"""Erros de negocio do modulo de compras."""

from fastapi import status

from app.core.erros import ErroDeNegocio


class PedidoNaoEncontrado(ErroDeNegocio):
    status_code = status.HTTP_404_NOT_FOUND
    detalhe = "Pedido nao encontrado"


class ItemPedidoNaoEncontrado(ErroDeNegocio):
    status_code = status.HTTP_404_NOT_FOUND
    detalhe = "Item do pedido nao encontrado"


class PagamentoNaoEncontrado(ErroDeNegocio):
    status_code = status.HTTP_404_NOT_FOUND
    detalhe = "Pagamento nao encontrado"


class CompraDuplicada(ErroDeNegocio):
    status_code = status.HTTP_409_CONFLICT
    detalhe = "Registro de compra ja existe"


class ReferenciaCompraInvalida(ErroDeNegocio):
    status_code = status.HTTP_409_CONFLICT
    detalhe = "Alguma referencia da compra nao existe ou nao pode ser usada"
