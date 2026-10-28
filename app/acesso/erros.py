"""Erros do login por CPF."""

from fastapi import status

from app.core.erros import ErroDeNegocio


class CpfOuSenhaIncorretos(ErroDeNegocio):
    """Um texto so para CPF sem cadastro, conta sem login e senha errada (nao revela clientes)."""

    status_code = status.HTTP_401_UNAUTHORIZED
    detalhe = "CPF ou senha incorretos."


class EmailNaoConfirmado(ErroDeNegocio):
    # O Supabase so diz isso depois de conferir a senha: nao ajuda a descobrir contas alheias.
    status_code = status.HTTP_403_FORBIDDEN
    detalhe = "Confirme seu e-mail primeiro: enviamos um link para a sua caixa de entrada."


class MuitasTentativasDeLogin(ErroDeNegocio):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    detalhe = "Muitas tentativas de login. Aguarde um minuto e tente de novo."


class LoginIndisponivel(ErroDeNegocio):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    detalhe = "O login está indisponível no momento. Tente de novo em instantes."
