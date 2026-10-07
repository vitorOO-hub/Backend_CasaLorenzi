"""Corpos aceitos pelas rotas de escrita do estoque. Campo desconhecido e recusado (422)."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Sku = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
Motivo = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)]
MotivoLongo = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=300)]


class Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NovaMovimentacao(Entrada):
    sku: Sku
    tipo: Literal["entrada", "saida"]
    quantidade: int = Field(ge=1, le=100_000, strict=True)
    motivo: Motivo
    # So o admin informa a loja; para os demais vale a do token (outra loja da 403).
    id_loja: UUID | None = None


class NovoAjuste(Entrada):
    sku: Sku
    quantidade_contada: int = Field(ge=0, le=100_000, strict=True)
    motivo: MotivoLongo
    id_loja: UUID | None = None


class Recusa(Entrada):
    motivo: MotivoLongo
