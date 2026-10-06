"""Modelos de entrada do modulo de estoque.

Nenhum modelo de entrada pode ter campos de permissao (papel, id de usuario ou de cliente):
esses valores vem do token (CLAUDE.md, secao 3).
"""

from pydantic import BaseModel, ConfigDict, Field


class EntradaRestrita(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EstoqueCriacao(EntradaRestrita):
    id_loja: str | int
    id_variacao: str | int
    quantidade: int = Field(default=0, ge=0)
    estoque_minimo: int = Field(default=0, ge=0)


class QuantidadeEntrada(EntradaRestrita):
    quantidade: int = Field(gt=0)


class EstoqueMinimoEntrada(EntradaRestrita):
    estoque_minimo: int = Field(ge=0)
