"""Admin API do Supabase Auth (criar, convidar e apagar usuario).

A service role key vem do ambiente do servidor e nunca vai para log, resposta ou front.
"""

import logging
from collections.abc import Iterator
from typing import Annotated, Protocol
from uuid import UUID

import httpx
from fastapi import Depends

from app.ativacao.erros import AtivacaoIndisponivel, EmailJaNoAuth, SenhaRecusada
from app.core.config import Settings, get_settings

registro = logging.getLogger("app.ativacao")
TIMEOUT_SEGUNDOS = 10.0
CODIGOS_EMAIL_EXISTE = frozenset({"email_exists", "user_already_exists"})


class AuthAdmin(Protocol):
    def criar_usuario(self, email: str, senha: str) -> UUID: ...

    def convidar_usuario(self, email: str, redirect_to: str | None = None) -> UUID: ...

    def apagar_usuario(self, id_auth: UUID) -> None: ...


class AuthAdminSupabase:
    def __init__(self, url: str, chave: str, *, cliente: httpx.Client | None = None) -> None:
        self._base = f"{url}/auth/v1/admin/users"
        self._cabecalhos = {"apikey": chave, "Authorization": f"Bearer {chave}"}
        self._proprio = cliente is None
        self._cliente = cliente or httpx.Client(timeout=TIMEOUT_SEGUNDOS)

    def fechar(self) -> None:
        """Fecha as conexoes do cliente HTTP criado aqui (o recebido de fora e de quem o criou)."""
        if self._proprio:
            self._cliente.close()

    def criar_usuario(self, email: str, senha: str) -> UUID:
        try:
            resposta = self._cliente.post(
                self._base,
                headers=self._cabecalhos,
                json={"email": email, "password": senha, "email_confirm": True},
            )
        except httpx.HTTPError as erro:
            registro.error("Auth indisponivel ao criar usuario: %s", type(erro).__name__)
            raise AtivacaoIndisponivel from erro
        if resposta.is_success:
            return UUID(resposta.json()["id"])
        codigo = _codigo_do_erro(resposta)
        if codigo in CODIGOS_EMAIL_EXISTE:
            raise EmailJaNoAuth
        if codigo == "weak_password":
            raise SenhaRecusada
        # Sem o corpo no log: ele pode ecoar o e-mail ou a senha enviados.
        registro.error("Auth recusou a criacao: status=%s codigo=%s", resposta.status_code, codigo)
        raise AtivacaoIndisponivel

    def convidar_usuario(self, email: str, redirect_to: str | None = None) -> UUID:
        parametros = {"redirect_to": redirect_to} if redirect_to else None
        try:
            resposta = self._cliente.post(
                f"{self._base.removesuffix('/admin/users')}/invite",
                headers=self._cabecalhos,
                params=parametros,
                json={"email": email},
            )
        except httpx.HTTPError as erro:
            registro.error("Auth indisponivel ao convidar usuario: %s", type(erro).__name__)
            raise AtivacaoIndisponivel from erro
        if resposta.is_success:
            try:
                return UUID(resposta.json()["id"])
            except (KeyError, TypeError, ValueError):
                registro.error("Auth respondeu sem um id valido ao convidar usuario")
                raise AtivacaoIndisponivel from None
        codigo = _codigo_do_erro(resposta)
        if codigo in CODIGOS_EMAIL_EXISTE:
            raise EmailJaNoAuth
        registro.error("Auth recusou o convite: status=%s codigo=%s", resposta.status_code, codigo)
        raise AtivacaoIndisponivel

    def apagar_usuario(self, id_auth: UUID) -> None:
        try:
            resposta = self._cliente.delete(f"{self._base}/{id_auth}", headers=self._cabecalhos)
            if not resposta.is_success:
                registro.error("Auth nao apagou %s: status=%s", id_auth, resposta.status_code)
        except httpx.HTTPError as erro:
            registro.error("Auth indisponivel ao apagar %s: %s", id_auth, type(erro).__name__)


def _codigo_do_erro(resposta: httpx.Response) -> str | None:
    try:
        corpo = resposta.json()
    except ValueError:
        return None
    return corpo.get("error_code") if isinstance(corpo, dict) else None


def get_auth_admin(settings: Annotated[Settings, Depends(get_settings)]) -> Iterator[AuthAdmin]:
    """Um cliente do Admin API por requisicao, fechado no fim dela (mesmo se a rota der erro)."""
    chave = settings.supabase_service_role_key
    if not settings.supabase_url or chave is None:
        raise AtivacaoIndisponivel
    admin = AuthAdminSupabase(settings.supabase_url, chave.get_secret_value())
    try:
        yield admin
    finally:
        admin.fechar()


AuthAdminDep = Annotated[AuthAdmin, Depends(get_auth_admin)]
