"""Erros de negocio do modulo de atendimento."""

from fastapi import status

from app.core.erros import ErroDeNegocio


class AtendimentoNaoEncontrado(ErroDeNegocio):
    status_code = status.HTTP_404_NOT_FOUND
    detalhe = "Atendimento nao encontrado"


class RegistroAtendimentoDuplicado(ErroDeNegocio):
    status_code = status.HTTP_409_CONFLICT
    detalhe = "Registro de atendimento ja existe"


class ReferenciaAtendimentoInvalida(ErroDeNegocio):
    status_code = status.HTTP_409_CONFLICT
    detalhe = "Alguma referencia do atendimento nao existe ou nao pode ser usada"


class AtendimentoInvalido(ErroDeNegocio):
    status_code = status.HTTP_409_CONFLICT
    detalhe = "Atendimento invalido para os dados informados"
