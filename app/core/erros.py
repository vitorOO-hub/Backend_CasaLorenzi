"""Erros de negocio: cada modulo declara os seus, e um unico tratador gera a resposta HTTP.

Convencao da API (CLAUDE.md, secao 6): 404 nao encontrado, 409 estado nao permite a acao,
mensagens em portugues.
"""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse


class ErroDeNegocio(Exception):
    """Base dos erros previstos pelas regras de negocio. Subclasses definem status e mensagem."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    detalhe: str = "Requisicao invalida"


def registrar_tratadores(app: FastAPI) -> None:
    @app.exception_handler(ErroDeNegocio)
    async def tratar_erro_de_negocio(_request: Request, erro: ErroDeNegocio) -> JSONResponse:
        return JSONResponse({"detail": erro.detalhe}, status_code=erro.status_code)
