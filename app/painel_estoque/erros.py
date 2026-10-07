"""Erros de negocio do estoque do painel. O tratador unico (app.core.erros) gera a resposta."""

from fastapi import status

from app.core.erros import ErroDeNegocio


class PecaNaoEncontrada(ErroDeNegocio):
    status_code = status.HTTP_404_NOT_FOUND
    detalhe = "Peca nao encontrada"


class SaldoInsuficiente(ErroDeNegocio):
    status_code = status.HTTP_409_CONFLICT

    def __init__(self, disponivel: int) -> None:
        self.detalhe = f"Saldo insuficiente: ha {disponivel} unidade(s) em estoque"
        super().__init__(self.detalhe)


class LojaObrigatoria(ErroDeNegocio):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    detalhe = "Informe a loja"


class SemDiferenca(ErroDeNegocio):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    detalhe = "A quantidade contada e igual ao saldo do sistema: nao ha o que ajustar"


class AjusteNaoEncontrado(ErroDeNegocio):
    """Tambem cobre ajuste de outra loja: nao revelamos que ele existe."""

    status_code = status.HTTP_404_NOT_FOUND
    detalhe = "Ajuste nao encontrado"


class AjusteJaDecidido(ErroDeNegocio):
    status_code = status.HTTP_409_CONFLICT
    detalhe = "Este ajuste ja foi decidido"
