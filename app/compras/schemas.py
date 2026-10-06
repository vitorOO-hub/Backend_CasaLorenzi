"""Schemas do modulo de compras."""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class EntradaRestrita(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SaidaFlexivel(BaseModel):
    model_config = ConfigDict(extra="allow")


class PedidoCriacao(EntradaRestrita):
    numero_pedido: str = Field(min_length=1, max_length=80)
    id_loja: str | int
    id_cliente: str | int
    id_usuario_responsavel: str | int | None = None
    id_status_pedido: str | int
    valor_total: Decimal = Field(default=Decimal("0.00"), ge=0, decimal_places=2)
    observacao: str | None = Field(default=None, max_length=1000)


class PedidoAtualizacao(EntradaRestrita):
    id_usuario_responsavel: str | int | None = None
    id_status_pedido: str | int | None = None
    valor_total: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    observacao: str | None = Field(default=None, max_length=1000)


class StatusPedidoAtualizacao(EntradaRestrita):
    id_status_pedido: str | int


class ItemPedidoCriacao(EntradaRestrita):
    id_variacao: str | int
    quantidade: int = Field(gt=0)
    preco_unitario: Decimal = Field(ge=0, decimal_places=2)


class ItemPedidoAtualizacao(EntradaRestrita):
    quantidade: int | None = Field(default=None, gt=0)
    preco_unitario: Decimal | None = Field(default=None, ge=0, decimal_places=2)


class PagamentoCriacao(EntradaRestrita):
    tentativa: int = Field(default=1, gt=0)
    id_metodo_pagamento: str | int
    id_status_pagamento: str | int
    valor: Decimal = Field(gt=0, decimal_places=2)
    transacao_externa_id: str | None = Field(default=None, max_length=160)
    processado_em: str | None = None


class StatusPagamentoAtualizacao(EntradaRestrita):
    id_status_pagamento: str | int
    transacao_externa_id: str | None = Field(default=None, max_length=160)
    processado_em: str | None = None


class RegistroCompraLeitura(SaidaFlexivel):
    pass
