"""Schemas do fluxo de transferencia e reposicao de estoque."""

from pydantic import BaseModel, ConfigDict, Field


class TransferenciaCriacao(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id_loja_origem: str | int
    id_variacao: str | int
    quantidade: int = Field(gt=0)
    observacao: str | None = Field(default=None, max_length=1000)


class ReposicaoCriacao(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id_variacao: str | int
    quantidade: int = Field(gt=0)
    observacao: str | None = Field(default=None, max_length=1000)


class TransferenciaLeitura(BaseModel):
    model_config = ConfigDict(extra="allow")
