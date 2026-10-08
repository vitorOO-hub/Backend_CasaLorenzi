"""Erros da API: cada modulo declara os de negocio, e tratadores unicos geram a resposta HTTP.

Convencao da API (CLAUDE.md, secao 6): 404 nao encontrado, 409 estado nao permite a acao,
422 validacao, mensagens em portugues e sem detalhe interno (sem stack, SQL ou corpo enviado).
"""

import logging

from fastapi import FastAPI, Request, status
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

registro = logging.getLogger("app.erros")


class ErroDeNegocio(Exception):
    """Base dos erros previstos pelas regras de negocio. Subclasses definem status e mensagem."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    detalhe: str = "Requisicao invalida"


# Tipos de erro do Pydantic -> mensagem para a pessoa. O texto original esta em ingles e pode ecoar
# o valor enviado, entao nunca vai para a resposta.
MENSAGENS_DE_VALIDACAO = {
    "missing": "Campo obrigatorio",
    "extra_forbidden": "Campo nao permitido",
    "string_type": "Informe um texto",
    "string_too_short": "Texto curto demais",
    "string_too_long": "Texto longo demais",
    "string_pattern_mismatch": "Formato invalido",
    "int_parsing": "Informe um numero inteiro",
    "int_type": "Informe um numero inteiro",
    "float_parsing": "Informe um numero",
    "decimal_parsing": "Informe um valor numerico",
    "decimal_type": "Informe um valor numerico",
    "decimal_max_places": "Casas decimais demais",
    "bool_parsing": "Informe verdadeiro ou falso",
    "uuid_parsing": "Identificador invalido",
    "date_parsing": "Data invalida",
    "date_from_datetime_parsing": "Data invalida",
    "greater_than": "Valor menor do que o permitido",
    "greater_than_equal": "Valor menor do que o permitido",
    "less_than": "Valor maior do que o permitido",
    "less_than_equal": "Valor maior do que o permitido",
    "literal_error": "Valor nao aceito",
    "enum": "Valor nao aceito",
    "too_short": "Itens de menos",
    "too_long": "Itens demais",
    "json_invalid": "JSON invalido",
}


def _campo(loc: tuple) -> str:
    partes = [str(p) for p in loc if p not in ("body", "query", "path", "header")]
    return ".".join(partes) or "corpo"


def _mensagem(erro: dict) -> str:
    if erro.get("type") == "value_error":
        # Mensagens que nos mesmos escrevemos nos validadores ("Informe o que mudar").
        texto = str(erro.get("msg", "")).removeprefix("Value error, ").strip()
        return texto or "Valor invalido"
    return MENSAGENS_DE_VALIDACAO.get(str(erro.get("type")), "Valor invalido")


def registrar_tratadores(app: FastAPI) -> None:
    @app.exception_handler(ErroDeNegocio)
    async def tratar_erro_de_negocio(_request: Request, erro: ErroDeNegocio) -> JSONResponse:
        return JSONResponse({"detail": erro.detalhe}, status_code=erro.status_code)

    @app.exception_handler(RequestValidationError)
    async def tratar_validacao(_request: Request, erro: RequestValidationError) -> JSONResponse:
        campos = [
            {"campo": _campo(tuple(e["loc"])), "mensagem": _mensagem(e)} for e in erro.errors()
        ]
        resumo = "; ".join(f"{c['campo']}: {c['mensagem']}" for c in campos[:3])
        return JSONResponse(
            {"detail": f"Dados invalidos ({resumo})", "campos": campos},
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    @app.exception_handler(StarletteHTTPException)
    async def tratar_http(request: Request, erro: StarletteHTTPException) -> JSONResponse:
        # 404/405 do roteador chegam com texto em ingles; os demais (401 com WWW-Authenticate...)
        # seguem o tratador padrao, que preserva os cabecalhos.
        if erro.status_code == status.HTTP_404_NOT_FOUND and erro.detail == "Not Found":
            return JSONResponse({"detail": "Rota nao encontrada"}, status_code=404)
        if (
            erro.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
            and erro.detail == "Method Not Allowed"
        ):
            return JSONResponse(
                {"detail": "Metodo nao permitido"}, status_code=405, headers=erro.headers
            )
        return await http_exception_handler(request, erro)

    @app.exception_handler(Exception)
    async def tratar_inesperado(request: Request, erro: Exception) -> JSONResponse:
        # Detalhe so no log do servidor; a resposta nao revela nada interno.
        registro.error("erro inesperado em %s %s", request.method, request.url.path, exc_info=erro)
        return JSONResponse(
            {"detail": "Erro interno. Tente de novo em instantes."}, status_code=500
        )
