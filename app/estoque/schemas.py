"""Modelos de entrada do modulo de estoque.

Nenhum modelo de entrada pode ter campos de permissao (papel, id de usuario ou de cliente):
esses valores vem do token (CLAUDE.md, secao 3).
"""

from pydantic import BaseModel, Field


class QuantidadeEntrada(BaseModel):
    quantidade: int = Field(gt=0)
    motivo: str | None = Field(default=None, max_length=1000)


class AjusteInventarioEntrada(BaseModel):
    quantidade: int = Field(ge=0)
    motivo: str | None = Field(default=None, max_length=1000)
