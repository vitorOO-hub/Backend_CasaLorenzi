"""Autenticacao via Supabase Auth e autorizacao por perfil de usuario."""

from collections.abc import Callable
from functools import lru_cache
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError, PyJWTError
from pydantic import BaseModel, ConfigDict

from app.core.config import Settings, get_settings
from app.core.db import ExecutarDep
from app.core.repositorio import buscar_um, serializar_linha

ALGORITMO = "ES256"
AUDIENCIA = "authenticated"
TAMANHO_MAXIMO_TOKEN = 8 * 1024

MENSAGEM_NAO_AUTENTICADO = "Token invalido ou expirado"
MENSAGEM_SEM_PERMISSAO = "Sem permissao para esta acao"
MENSAGEM_AUTH_INDISPONIVEL = "Servico de autenticacao indisponivel"

esquema_bearer = HTTPBearer(
    auto_error=False,
    description="Access token emitido pelo Supabase Auth",
)


class UsuarioAtual(BaseModel):
    model_config = ConfigDict(frozen=True)

    id_usuario: str
    auth_user_id: str
    nome: str
    email: str
    tipo_usuario_codigo: str
    tipo_usuario: str
    id_loja: str | None = None


def _erro_nao_autenticado() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=MENSAGEM_NAO_AUTENTICADO,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _erro_sem_permissao() -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=MENSAGEM_SEM_PERMISSAO)


def _erro_auth_indisponivel() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=MENSAGEM_AUTH_INDISPONIVEL,
    )


@lru_cache
def _cliente_jwks(url: str) -> PyJWKClient:
    return PyJWKClient(url)


def _validar_claims(token: str, settings: Settings) -> dict[str, object]:
    if not token or len(token) > TAMANHO_MAXIMO_TOKEN or not token.isascii():
        raise _erro_nao_autenticado()
    if not settings.supabase_issuer or not settings.supabase_jwks_url:
        raise _erro_auth_indisponivel()

    try:
        cabecalho = jwt.get_unverified_header(token)
    except (PyJWTError, ValueError) as erro:
        raise _erro_nao_autenticado() from erro

    if cabecalho.get("alg") != ALGORITMO:
        raise _erro_nao_autenticado()

    try:
        chave = _cliente_jwks(settings.supabase_jwks_url).get_signing_key_from_jwt(token).key
    except PyJWKClientConnectionError as erro:
        raise _erro_auth_indisponivel() from erro
    except PyJWKClientError as erro:
        raise _erro_nao_autenticado() from erro

    try:
        claims = jwt.decode(
            token,
            chave,
            algorithms=[ALGORITMO],
            audience=AUDIENCIA,
            issuer=settings.supabase_issuer,
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
    except (PyJWTError, ValueError) as erro:
        raise _erro_nao_autenticado() from erro

    if claims.get("role") != AUDIENCIA or claims.get("is_anonymous") is True:
        raise _erro_nao_autenticado()
    return claims


def _buscar_usuario_atual(executar: ExecutarDep, auth_user_id: UUID) -> UsuarioAtual:
    def operacao(conexao):
        linha = buscar_um(
            conexao,
            """
            SELECT
                u.id_usuario,
                u.auth_user_id,
                u.nome,
                u.email,
                u.id_loja,
                t.codigo AS tipo_usuario_codigo,
                t.nome AS tipo_usuario
            FROM usuario u
            JOIN tipo_usuario t ON t.id_tipo_usuario = u.id_tipo_usuario
            WHERE u.auth_user_id = %s
              AND u.ativo
              AND t.ativo
            """,
            (auth_user_id,),
        )
        return serializar_linha(linha) if linha else None

    dados = executar(operacao)
    if not dados:
        raise _erro_nao_autenticado()
    return UsuarioAtual(**dados)


def get_current_user(
    credenciais: Annotated[HTTPAuthorizationCredentials | None, Depends(esquema_bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
    executar: ExecutarDep,
) -> UsuarioAtual:
    if credenciais is None or credenciais.scheme.lower() != "bearer":
        raise _erro_nao_autenticado()

    claims = _validar_claims(credenciais.credentials, settings)
    try:
        auth_user_id = UUID(str(claims["sub"]))
    except (KeyError, ValueError) as erro:
        raise _erro_nao_autenticado() from erro
    return _buscar_usuario_atual(executar, auth_user_id)


def requer_papeis(*codigos_permitidos: str) -> Callable[[UsuarioAtual], UsuarioAtual]:
    permitidos = set(codigos_permitidos)

    def dependencia(usuario: Annotated[UsuarioAtual, Depends(get_current_user)]) -> UsuarioAtual:
        if usuario.tipo_usuario_codigo not in permitidos:
            raise _erro_sem_permissao()
        return usuario

    return dependencia
