"""Apoio dos testes de autenticacao: chaves ES256 de mentira e emissao de tokens."""

import time
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from jwt.algorithms import ECAlgorithm

from app.core.jwks import ProvedorChaves

SUPABASE_URL = "https://projeto-teste.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"
URL_JWKS = f"{ISSUER}/.well-known/jwks.json"
KID_PADRAO = "chave-de-teste"

# Valor que, passado a `emitir`, remove a claim do token.
REMOVER = object()


class ParDeChaves:
    def __init__(self, kid: str = KID_PADRAO) -> None:
        self.kid = kid
        self.privada = ec.generate_private_key(ec.SECP256R1())

    @property
    def jwk(self) -> dict:
        publica = ECAlgorithm.to_jwk(self.privada.public_key(), as_dict=True)
        return {**publica, "kid": self.kid, "alg": "ES256", "use": "sig"}

    def emitir(self, **claims) -> str:
        agora = int(time.time())
        payload = {
            "sub": str(uuid4()),
            "aud": "authenticated",
            "iss": ISSUER,
            "role": "authenticated",
            "iat": agora,
            "exp": agora + 900,
        }
        payload.update(claims)
        payload = {nome: valor for nome, valor in payload.items() if valor is not REMOVER}
        return jwt.encode(payload, self.privada, algorithm="ES256", headers={"kid": self.kid})


def provedor_para(par: ParDeChaves) -> ProvedorChaves:
    return ProvedorChaves(URL_JWKS, buscar=lambda: {"keys": [par.jwk]})
