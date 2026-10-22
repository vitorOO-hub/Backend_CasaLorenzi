"""Erros da ativacao de conta do cliente importado."""

from fastapi import status

from app.core.erros import ErroDeNegocio


class AtivacaoNegada(ErroDeNegocio):
    """Um texto so para tudo (CPF sem cadastro, conta ja ativa, e-mail em uso): quem consulta
    nao descobre quais CPFs existem."""

    status_code = status.HTTP_409_CONFLICT
    detalhe = (
        "Nao foi possivel ativar esta conta. Se voce ja ativou, e so entrar com seu e-mail e "
        "sua senha. Se nao, procure uma loja."
    )


class EmailObrigatorio(ErroDeNegocio):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    detalhe = "Informe seu e-mail"


class SenhaRecusada(ErroDeNegocio):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    detalhe = "Senha recusada. Use pelo menos 8 caracteres, com letras e numeros"


class AtivacaoIndisponivel(ErroDeNegocio):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    detalhe = "A ativacao de conta esta indisponivel no momento. Tente de novo em instantes."


class EmailJaNoAuth(Exception):
    """O Auth ja tem uma conta com este e-mail."""
