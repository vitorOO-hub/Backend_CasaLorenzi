"""Schemas do login por CPF (rota publica)."""

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EntradaCpf(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cpf: str
    senha: str = Field(min_length=1, max_length=72)

    @field_validator("cpf")
    @classmethod
    def _cpf(cls, valor: str) -> str:
        digitos = re.sub(r"\D", "", valor)
        if len(digitos) != 11:
            raise ValueError("Informe o CPF com 11 numeros")
        return digitos


class SessaoSupabase(BaseModel):
    """Os mesmos tokens que o login por e-mail do Supabase entrega ao navegador."""

    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "bearer"
