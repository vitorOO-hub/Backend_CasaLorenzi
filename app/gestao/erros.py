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
