"""Schemas das vendas em loja. Quem vende e a loja vem do token, nunca do corpo."""

import re
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

Metodo = Literal["cartao_credito", "cartao_debito", "pix", "dinheiro"]
Busca = Annotated[str, Field(max_length=80)]


class Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Saida(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def so_digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor)


class BuscaDeCliente(Entrada):
    cpf: str

    @field_validator("cpf")
    @classmethod
    def _cpf(cls, valor: str) -> str:
        digitos = so_digitos(valor)
        if len(digitos) != 11:
            raise ValueError("Informe o CPF com 11 numeros")
        return digitos


class ItemDaVenda(Entrada):
    id_variacao: UUID
    quantidade: int = Field(ge=1, le=99)


class NovaVenda(BuscaDeCliente):
    itens: list[ItemDaVenda] = Field(min_length=1, max_length=50)
    metodo_pagamento: Metodo
    # Regra da operacao: troca na loja entra como venda nova com a observacao "troca".
    observacao: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None = (
        None
    )


class ClienteDaVenda(Saida):
    id_cliente: UUID
    nome: str
    cpf: str
    email: str | None
    telefone: str | None


class ItemDeCliente(ClienteDaVenda):
    cidade: str | None
    cliente_desde: datetime


class ListaDeClientes(Saida):
    total: int
    itens: list[ItemDeCliente]


class ItemDeVenda(Saida):
    id_pedido: UUID
    numero_pedido: str
    criado_em: datetime
    canal_venda: str
    loja: str
    cliente: str
    vendedor: str | None
    status_codigo: str
    status: str
    pecas: int
    valor_total: Decimal


class ListaDeVendas(Saida):
    total: int
    itens: list[ItemDeVenda]


class PecaDaVenda(Saida):
    sku: str
    produto: str
    cor: str | None
    tamanho: str | None
    quantidade: int
    preco_unitario: Decimal
    valor_total: Decimal


class DetalheDaVenda(ItemDeVenda):
    cliente_cpf: str
    metodo_pagamento: str | None
    observacao: str | None
    itens_da_venda: list[PecaDaVenda]


class PecaNoEstoque(Saida):
    id_variacao: UUID
    sku: str
    produto: str
    cor: str | None
    tamanho: str | None
    preco_venda: Decimal
    disponivel: int


class OpcaoDePagamento(Saida):
    codigo: str
    nome: str


class OpcoesDeVenda(Saida):
    metodos: list[OpcaoDePagamento]
    loja: str | None
