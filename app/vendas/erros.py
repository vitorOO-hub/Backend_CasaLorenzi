"""Erros das vendas em loja."""

from fastapi import status

from app.core.erros import ErroDeNegocio


class ClienteNaoEncontrado(ErroDeNegocio):
    status_code = status.HTTP_404_NOT_FOUND
    detalhe = "Nenhum cliente cadastrado com este CPF"


class VendaNaoEncontrada(ErroDeNegocio):
    status_code = status.HTTP_404_NOT_FOUND
    detalhe = "Venda nao encontrada"


class PecaIndisponivel(ErroDeNegocio):
    status_code = status.HTTP_404_NOT_FOUND
    detalhe = "Peca nao encontrada no estoque desta loja"


class EstoqueInsuficiente(ErroDeNegocio):
    status_code = status.HTTP_409_CONFLICT

    def __init__(self, sku: str, disponivel: int) -> None:
        self.detalhe = f"{sku}: restam {disponivel} unidades em estoque"


class VendaNaoRegistrada(ErroDeNegocio):
    """O banco recusou a gravacao (por exemplo, duas vendas mexendo na mesma peca ao mesmo tempo).
    Nada foi gravado: a transacao inteira volta."""

    status_code = status.HTTP_409_CONFLICT
    detalhe = "Nao foi possivel registrar a venda agora. Confira as pecas e tente de novo."


class LojaDaVendaInvalida(ErroDeNegocio):
    status_code = status.HTTP_409_CONFLICT
    detalhe = "Sua conta nao esta ligada a uma loja ativa"


class ReferenciaDeVendaInvalida(ErroDeNegocio):
    status_code = status.HTTP_409_CONFLICT
    detalhe = "Configuracao de vendas incompleta no banco"
