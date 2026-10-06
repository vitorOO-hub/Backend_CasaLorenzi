"""Modelos de entrada do modulo de estoque.

Nenhum modelo de entrada pode ter campos de permissao (papel, id de usuario ou de cliente):
esses valores vem do token (CLAUDE.md, secao 3).
"""

from pydantic import BaseModel, Field


class EstoqueCriacao(BaseModel):
    id_loja: str | int
    id_variacao: str | int
    quantidade: int = Field(default=0, ge=0)
    estoque_minimo: int = Field(default=0, ge=0)


class QuantidadeEntrada(BaseModel):
    quantidade: int = Field(gt=0)


class EstoqueMinimoEntrada(BaseModel):
    estoque_minimo: int = Field(ge=0)
