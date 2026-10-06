"""Schemas da tabela movimentacao_estoque."""

from pydantic import BaseModel, ConfigDict, Field


class MovimentacaoCriacao(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id_loja: str | int
    id_variacao: str | int
    id_pedido: str | int | None = None
    id_usuario_responsavel: str | int | None = None
    id_tipo_movimentacao_estoque: str | int
    quantidade: int = Field(gt=0)
    quantidade_anterior: int = Field(ge=0)
    quantidade_posterior: int = Field(ge=0)
    motivo: str | None = Field(default=None, max_length=1000)


class MovimentacaoLeitura(BaseModel):
    model_config = ConfigDict(extra="allow")
