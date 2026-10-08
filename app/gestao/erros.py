"""Erros de negocio da gestao do admin. O tratador unico (app.core.erros) gera a resposta."""

from fastapi import status

from app.core.erros import ErroDeNegocio


class UsuarioNaoEncontrado(ErroDeNegocio):
    """Tambem cobre cliente: esta tela so mexe no time interno."""

    status_code = status.HTTP_404_NOT_FOUND
    detalhe = "Usuario nao encontrado"


class LojaDoUsuarioInvalida(ErroDeNegocio):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    detalhe = "Escolha uma loja ativa para este cargo"


class NaoPodeMudarOProprioAcesso(ErroDeNegocio):
    status_code = status.HTTP_409_CONFLICT
    detalhe = "Voce nao pode desativar nem rebaixar a propria conta"


class UltimoAdministrador(ErroDeNegocio):
    status_code = status.HTTP_409_CONFLICT
    detalhe = "A rede precisa de pelo menos um administrador ativo"


class PecaNaoEncontrada(ErroDeNegocio):
    status_code = status.HTTP_404_NOT_FOUND
    detalhe = "Peca nao encontrada"


class SkuJaExiste(ErroDeNegocio):
    status_code = status.HTTP_409_CONFLICT
    detalhe = "Ja existe uma peca com este SKU"


class NomeDePecaJaExiste(ErroDeNegocio):
    status_code = status.HTTP_409_CONFLICT
    detalhe = "Ja existe uma peca com este nome"


class PecaEmUso(ErroDeNegocio):
    status_code = status.HTTP_409_CONFLICT
    detalhe = "Peca com estoque, pedidos ou historico de estoque nao pode ser excluida"


class RegistroNaoEncontrado(ErroDeNegocio):
    status_code = status.HTTP_404_NOT_FOUND
    detalhe = "Registro de importacao nao encontrado"


class RegistroJaMapeado(ErroDeNegocio):
    status_code = status.HTTP_409_CONFLICT
    detalhe = "Este registro ja foi mapeado"


class SkuInvalido(ErroDeNegocio):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    detalhe = "Escolha um SKU ativo do catalogo"
