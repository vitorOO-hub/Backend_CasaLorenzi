"""Login do cliente por CPF.

O navegador manda CPF e senha; o servidor acha o e-mail da conta pelo CPF e pede a sessao ao
Supabase Auth (grant de senha), devolvendo so os tokens. O e-mail nunca sai do servidor, e CPF sem
conta, conta sem login e senha errada recebem a mesma resposta. Vale so para cliente: a equipe
entra por e-mail. Limite por IP na borda (app/core/protecoes.py).
"""

import logging
from typing import Any, Protocol

import httpx
from sqlalchemy.engine import Connection

from app.acesso.erros import (
    CpfOuSenhaIncorretos,
    EmailNaoConfirmado,
    LoginIndisponivel,
    MuitasTentativasDeLogin,
)
from app.core.repositorio import buscar_um

registro = logging.getLogger("app.acesso")
TIMEOUT_SEGUNDOS = 10.0
CODIGOS_CREDENCIAIS = frozenset({"invalid_credentials", "invalid_grant", "user_not_found"})


class LoginAuth(Protocol):
    def entrar(self, email: str, senha: str) -> dict[str, Any]: ...


class LoginSupabase:
    def __init__(self, url: str, chave: str, *, cliente: httpx.Client | None = None) -> None:
        self._url = f"{url}/auth/v1/token"
        self._cabecalhos = {"apikey": chave}
        self._proprio = cliente is None
        self._cliente = cliente or httpx.Client(timeout=TIMEOUT_SEGUNDOS)

    def fechar(self) -> None:
        if self._proprio:
            self._cliente.close()

    def entrar(self, email: str, senha: str) -> dict[str, Any]:
        try:
            resposta = self._cliente.post(
                self._url,
                params={"grant_type": "password"},
                headers=self._cabecalhos,
                json={"email": email, "password": senha},
            )
        except httpx.HTTPError as erro:
            registro.error("Auth indisponivel no login por CPF: %s", type(erro).__name__)
            raise LoginIndisponivel from erro
        if resposta.is_success:
            try:
                return resposta.json()
            except ValueError:
                raise LoginIndisponivel from None
        codigo = _codigo_do_erro(resposta)
        if codigo == "email_not_confirmed":
            raise EmailNaoConfirmado
        if resposta.status_code == 429 or codigo == "over_request_rate_limit":
            raise MuitasTentativasDeLogin
        if resposta.status_code in (400, 401) and (codigo is None or codigo in CODIGOS_CREDENCIAIS):
            raise CpfOuSenhaIncorretos
        # Sem o corpo no log: ele pode ecoar o e-mail enviado.
        registro.error(
            "Auth recusou o login por CPF: status=%s codigo=%s", resposta.status_code, codigo
        )
        raise LoginIndisponivel


def email_do_cliente(conexao: Connection, cpf: str) -> str | None:
    """E-mail de login do cliente ativo com este CPF (o do Supabase Auth, nao o do cadastro)."""
    linha = buscar_um(
        conexao,
        """
        SELECT au.email
        FROM public.usuario u
        JOIN public.tipo_usuario t ON t.id_tipo_usuario = u.id_tipo_usuario
        JOIN auth.users au ON au.id = u.auth_user_id
        WHERE u.documento = %s
          AND t.codigo = 'cliente'
          AND u.ativo IS TRUE
          AND au.deleted_at IS NULL
          AND au.email IS NOT NULL
        """,
        (cpf,),
    )
    return linha["email"] if linha else None


def entrar_por_cpf(conexao: Connection, login: LoginAuth, cpf: str, senha: str) -> dict[str, Any]:
    email = email_do_cliente(conexao, cpf)
    if email is None:
        raise CpfOuSenhaIncorretos
    sessao = login.entrar(email, senha)
    try:
        return {
            "access_token": sessao["access_token"],
            "refresh_token": sessao["refresh_token"],
            "expires_in": int(sessao["expires_in"]),
            "token_type": sessao.get("token_type", "bearer"),
        }
    except (KeyError, TypeError, ValueError):
        registro.error("Auth respondeu o login por CPF sem os tokens esperados")
        raise LoginIndisponivel from None


def _codigo_do_erro(resposta: httpx.Response) -> str | None:
    try:
        corpo = resposta.json()
    except ValueError:
        return None
    if not isinstance(corpo, dict):
        return None
    codigo = corpo.get("error_code") or corpo.get("code")
    return codigo if isinstance(codigo, str) else None
