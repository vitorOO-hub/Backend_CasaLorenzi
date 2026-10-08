"""Validacao do JWT do Supabase e controle de acesso por papel (CLAUDE.md, secoes 3 e 12.7)."""

from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.erros_auth import AutenticacaoIndisponivel, NaoAutenticado, SemPermissao
from app.core.jwks import ProvedorChaves
from app.core.papeis import PAPEIS_COM_LOJA, Papel, UsuarioAtual

ALGORITMO = "ES256"
AUDIENCE = "authenticated"
TAMANHO_MAXIMO_TOKEN = 8192
CLAIMS_OBRIGATORIAS = ["exp", "sub", "aud", "iss"]
# Tolerancia de relogio entre o Supabase e a API, em segundos.
LEEWAY_SEGUNDOS = 30


def decodificar_token(token: str, *, provedor: ProvedorChaves, issuer: str) -> UsuarioAtual:
    """Valida assinatura, expiracao, audience e issuer e devolve o usuario das claims.

    Qualquer falha de validacao vira NaoAutenticado, sem dizer o motivo ao chamador.
    """
    if len(token) > TAMANHO_MAXIMO_TOKEN:
        raise NaoAutenticado()
    try:
        cabecalho = jwt.get_unverified_header(token)
        if cabecalho.get("alg") != ALGORITMO:
            raise NaoAutenticado()
        chave = provedor.obter_chave(cabecalho.get("kid"))
        claims = jwt.decode(
            token,
            chave,
            algorithms=[ALGORITMO],
            audience=AUDIENCE,
            issuer=issuer,
            leeway=LEEWAY_SEGUNDOS,
            options={"require": CLAIMS_OBRIGATORIAS},
        )
    except jwt.PyJWTError as erro:
        raise NaoAutenticado() from erro
    return _usuario_das_claims(claims)


def _usuario_das_claims(claims: dict) -> UsuarioAtual:
    if claims.get("is_anonymous") is True or claims.get("role") != "authenticated":
        raise NaoAutenticado()
    try:
        id_auth = UUID(str(claims["sub"]))
        papel_bruto = claims.get("papel")
        papel = Papel(papel_bruto) if papel_bruto is not None else None
        loja_bruta = claims.get("loja_id")
        id_loja = UUID(str(loja_bruta)) if loja_bruta is not None else None
    except (ValueError, TypeError, KeyError) as erro:
        raise NaoAutenticado() from erro

    # Papel de loja exige loja; admin e cliente nao podem ter loja.
    if (papel in PAPEIS_COM_LOJA) != (id_loja is not None):
        raise NaoAutenticado()
    return UsuarioAtual(id_auth=id_auth, papel=papel, id_loja=id_loja)


_esquema_bearer = HTTPBearer(auto_error=False, description="JWT do Supabase Auth")
CredenciaisDep = Annotated[HTTPAuthorizationCredentials | None, Depends(_esquema_bearer)]


def _provedor(request: Request) -> ProvedorChaves:
    provedor = getattr(request.app.state, "provedor_chaves", None)
    if provedor is None:
        provedor = ProvedorChaves(
            f"{request.app.state.settings.supabase_url}/auth/v1/.well-known/jwks.json"
        )
        request.app.state.provedor_chaves = provedor
    return provedor


def _autenticar(
    request: Request,
    credenciais: HTTPAuthorizationCredentials | None,
) -> UsuarioAtual:
    supabase_url = request.app.state.settings.supabase_url
    if not supabase_url:
        raise AutenticacaoIndisponivel()
    if credenciais is None:
        raise NaoAutenticado()
    return decodificar_token(
        credenciais.credentials,
        provedor=_provedor(request),
        issuer=f"{supabase_url}/auth/v1",
    )


def get_current_user(request: Request, credenciais: CredenciaisDep) -> UsuarioAtual:
    """Dependencia: o usuario do token, ou 401 (ou 503 se a autenticacao estiver indisponivel)."""
    return _autenticar(request, credenciais)


def requer_papel(*papeis: Papel):
    """Fabrica de dependencia: exige um dos papeis e devolve o usuario (403 se nao tiver)."""
    permitidos = frozenset(papeis)

    def dependencia(usuario: Annotated[UsuarioAtual, Depends(get_current_user)]) -> UsuarioAtual:
        if usuario.papel not in permitidos:
            raise SemPermissao()
        return usuario

    return dependencia


def garantir_escopo_de_loja(usuario: UsuarioAtual, id_loja: UUID) -> None:
    """Admin acessa qualquer loja; os demais so a propria (CLAUDE.md, secao 7)."""
    if not usuario.pode_acessar_loja(id_loja):
        raise SemPermissao()
