"""Erros da area do cliente."""

from fastapi import status

from app.core.erros import ErroDeNegocio


class CadastroClienteNaoEncontrado(ErroDeNegocio):
    status_code = status.HTTP_403_FORBIDDEN
    detalhe = "Cadastro de cliente ativo nao encontrado"


class LojaNaoEncontrada(ErroDeNegocio):
    status_code = status.HTTP_404_NOT_FOUND
    detalhe = "Loja nao encontrada"


class PedidoClienteNaoEncontrado(ErroDeNegocio):
    status_code = status.HTTP_404_NOT_FOUND
    detalhe = "Pedido nao encontrado na sua conta"


class VariacaoIndisponivel(ErroDeNegocio):
    status_code = status.HTTP_404_NOT_FOUND
    detalhe = "Peca nao encontrada no catalogo"


class ReferenciaCheckoutInvalida(ErroDeNegocio):
    status_code = status.HTTP_409_CONFLICT
    detalhe = "Configuracao de checkout incompleta no banco"


class EstoqueInsuficiente(ErroDeNegocio):
    status_code = status.HTTP_409_CONFLICT

    def __init__(self, sku: str, disponivel: int) -> None:
        self.detalhe = f"{sku}: restam {disponivel} unidades em estoque"


class ChamadoClienteNaoEncontrado(ErroDeNegocio):
    status_code = status.HTTP_404_NOT_FOUND
    detalhe = "Chamado nao encontrado na sua conta"


class ChamadoClienteFinalizado(ErroDeNegocio):
    status_code = status.HTTP_409_CONFLICT
    detalhe = "Este chamado ja foi finalizado"


class ReferenciaChamadoInvalida(ErroDeNegocio):
    status_code = status.HTTP_409_CONFLICT
    detalhe = "Configuracao de atendimento incompleta no banco"
