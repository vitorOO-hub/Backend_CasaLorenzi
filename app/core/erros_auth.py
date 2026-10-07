"""Erros de autenticacao e autorizacao (CLAUDE.md, secoes 6 e 12.6)."""

from fastapi import HTTPException, status

from app.core.erros import ErroDeNegocio


class NaoAutenticado(HTTPException):
    """401. Usa HTTPException porque a resposta precisa do cabecalho WWW-Authenticate."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalido ou ausente",
            headers={"WWW-Authenticate": "Bearer"},
        )


class SemPermissao(ErroDeNegocio):
    status_code = status.HTTP_403_FORBIDDEN
    detalhe = "Voce nao tem permissao para esta acao"


class AutenticacaoIndisponivel(ErroDeNegocio):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    detalhe = "Autenticacao temporariamente indisponivel"
