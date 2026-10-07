"""Validacao do JWT do Supabase e controle de acesso por papel (CLAUDE.md, secoes 3 e 12.7)."""

from uuid import UUID

import jwt

from app.core.erros_auth import NaoAutenticado
from app.core.jwks import ProvedorChaves
from app.core.papeis import PAPEIS_COM_LOJA, Papel, UsuarioAtual

ALGORITMO = "ES256"
AUDIENCE = "authenticated"
TAMANHO_MAXIMO_TOKEN = 8192
CLAIMS_OBRIGATORIAS = ["exp", "sub", "aud", "iss"]


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
