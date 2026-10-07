"""Erros de negocio da area de clientes do painel."""

from fastapi import status

from app.core.erros import ErroDeNegocio


class ClienteNaoEncontrado(ErroDeNegocio):
    """Tambem cobre cliente fora do escopo de loja: nao revelamos que ele existe."""

    status_code = status.HTTP_404_NOT_FOUND
    detalhe = "Cliente nao encontrado"
