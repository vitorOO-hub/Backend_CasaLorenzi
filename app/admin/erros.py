"""Erros de negocio do modulo administrativo."""

from fastapi import status

from app.core.erros import ErroDeNegocio


class RegistroAdminNaoEncontrado(ErroDeNegocio):
    status_code = status.HTTP_404_NOT_FOUND

    def __init__(self, recurso: str = "Registro") -> None:
        self.detalhe = f"{recurso} nao encontrado"


class RegistroAdminDuplicado(ErroDeNegocio):
    status_code = status.HTTP_409_CONFLICT

    def __init__(self, recurso: str = "Registro") -> None:
        self.detalhe = f"{recurso} ja existe"


class ReferenciaAdminInvalida(ErroDeNegocio):
    status_code = status.HTTP_409_CONFLICT
    detalhe = "Alguma referencia informada nao existe ou nao pode ser usada"
