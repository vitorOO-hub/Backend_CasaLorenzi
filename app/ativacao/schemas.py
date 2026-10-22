"""Schemas da ativacao de conta (rotas publicas: so CPF, senha e e-mail)."""

import re

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

SENHA_MINIMA = 8
SENHA_MAXIMA = 72  # limite do bcrypt


def _so_digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor)


class EntradaRestrita(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _ComCpf(EntradaRestrita):
    cpf: str

    @field_validator("cpf")
    @classmethod
    def _cpf(cls, valor: str) -> str:
        digitos = _so_digitos(valor)
        if len(digitos) != 11:
            raise ValueError("Informe o CPF com 11 numeros")
        return digitos


class ConsultaAtivacao(_ComCpf):
    pass


class AtivacaoConta(_ComCpf):
    senha: str
    email: EmailStr | None = None

    @field_validator("senha")
    @classmethod
    def _senha(cls, valor: str) -> str:
        if not SENHA_MINIMA <= len(valor) <= SENHA_MAXIMA:
            raise ValueError(f"A senha precisa de {SENHA_MINIMA} a {SENHA_MAXIMA} caracteres")
        if not re.search(r"[A-Za-z]", valor) or not re.search(r"\d", valor):
            raise ValueError("Use letras e numeros na senha")
        return valor


class RespostaConsulta(BaseModel):
    pede_email: bool


class RespostaAtivacao(BaseModel):
    # Mascarado ("j***@gmail.com"): a pessoa reconhece o e-mail, mas a tela nao o entrega.
    email: str
