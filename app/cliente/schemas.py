"""Schemas das rotas do cliente."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class EntradaRestrita(BaseModel):
    model_config = ConfigDict(extra="forbid")


CodigoBanco = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=40, pattern=r"^[a-z0-9_]+$"),
]
TextoCurto = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]
TextoLongo = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4000),
]


class ItemCheckout(EntradaRestrita):
    id_variacao: UUID
    quantidade: int = Field(gt=0, le=99)


class ItemCarrinhoCriacao(EntradaRestrita):
    id_variacao: UUID
    quantidade: int = Field(gt=0, le=99)


class ItemCarrinhoAtualizacao(EntradaRestrita):
    quantidade: int = Field(gt=0, le=99)


class ItemCarrinhoCliente(BaseModel):
    id_carrinho: UUID
    id_variacao: UUID
    sku: str
    produto: str
    imagem_url: str | None = None
    imagem_alt: str | None = None
    tecido: str | None = None
    cor: str
    tamanho: str
    quantidade: int
    preco_unitario: Decimal
    valor_total: Decimal


class CarrinhoCliente(BaseModel):
    itens: list[ItemCarrinhoCliente]
    subtotal: Decimal


class EnderecoEntrega(EntradaRestrita):
    cep: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=20)]
    rua: TextoCurto
    numero: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]
    complemento: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] | None = None
    uf: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=2)]


class CheckoutCriacao(EntradaRestrita):
    id_loja: UUID
    entrega: Literal["casa", "loja"]
    metodo_pagamento: Literal["cartao_credito", "pix", "boleto"]
    frete: Decimal = Field(default=Decimal("0.00"), ge=0, decimal_places=2)
    endereco_entrega: EnderecoEntrega | None = None
    itens: list[ItemCheckout] = Field(min_length=1, max_length=50)


class LojaCliente(BaseModel):
    id_loja: UUID
    nome: str
    cidade: str | None = None
    uf: str | None = None
    endereco: str | None = None


class PerfilCliente(BaseModel):
    id_cliente: UUID
    nome: str
    email: str
    telefone: str | None = None
    documento: str | None = None
    cliente_desde: datetime
    total_pedidos: int
    valor_total_pedidos: Decimal
    total_chamados: int
    id_loja_preferida: UUID | None = None
    loja_preferida: str | None = None


class ItemPedidoCliente(BaseModel):
    id_item_pedido: UUID
    id_variacao: UUID
    sku: str
    produto: str
    imagem_url: str | None = None
    imagem_alt: str | None = None
    tecido: str | None = None
    cor: str
    tamanho: str
    quantidade: int
    preco_unitario: Decimal
    valor_total: Decimal


class PagamentoCliente(BaseModel):
    id_pagamento: UUID
    metodo_codigo: str
    metodo: str
    status_codigo: str
    status: str
    valor: Decimal
    processado_em: datetime | None = None


class PedidoCliente(BaseModel):
    id_pedido: UUID
    numero_pedido: str
    id_loja: UUID
    loja: str
    status_codigo: str
    status: str
    valor_total: Decimal
    criado_em: datetime
    itens: list[ItemPedidoCliente]
    pagamento: PagamentoCliente | None = None


class OpcaoCliente(BaseModel):
    codigo: str
    nome: str


class OpcoesChamadoCliente(BaseModel):
    categorias: list[OpcaoCliente]


class ChamadoCriacao(EntradaRestrita):
    assunto: TextoCurto
    categoria: CodigoBanco
    descricao: TextoLongo
    id_loja: UUID | None = None
    id_pedido: UUID | None = None
    id_item_pedido: UUID | None = None


class MensagemChamadoCriacao(EntradaRestrita):
    texto: TextoLongo


class PecaChamadoCliente(BaseModel):
    id_item_pedido: UUID
    id_variacao: UUID
    sku: str
    produto: str
    cor: str
    tamanho: str
    quantidade: int


class AnexoChamadoCliente(BaseModel):
    id_anexo: UUID
    nome: str
    caminho: str
    criado_em: datetime


class ChamadoCliente(BaseModel):
    id_atendimento: UUID
    protocolo: str
    assunto: str
    categoria: OpcaoCliente
    status: OpcaoCliente
    id_pedido: UUID | None
    numero_pedido: str | None
    id_loja: UUID | None
    loja_nome: str | None
    aberto_em: datetime
    atualizado_em: datetime
    ultima_mensagem_em: datetime | None = None


class DetalheChamadoCliente(ChamadoCliente):
    pecas: list[PecaChamadoCliente]
    anexos: list[AnexoChamadoCliente]


class MensagemChamadoCliente(BaseModel):
    id_mensagem: UUID
    autor: Literal["cliente", "atendente"]
    nome: str
    texto: str
    enviada_em: datetime
