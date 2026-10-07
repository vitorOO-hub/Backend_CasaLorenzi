"""Erros de negocio do dashboard. O tratador unico (app.core.erros) gera a resposta."""

from fastapi import status

from app.core.erros import ErroDeNegocio


class PeriodoInvalido(ErroDeNegocio):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    detalhe = "Periodo invalido: a data final deve ser igual ou posterior a inicial"


class PeriodoLongoDemais(ErroDeNegocio):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    detalhe = "Periodo longo demais: o maximo e de 400 dias"
