"""Schemas do modulo administrativo."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class EntradaRestrita(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SaidaFlexivel(BaseModel):
    model_config = ConfigDict(extra="allow")


class LojaCriacao(EntradaRestrita):
    codigo: str = Field(min_length=1, max_length=80)
    nome: str = Field(min_length=1, max_length=160)
    cnpj: str | None = Field(default=None, max_length=20)
    email: EmailStr | None = None
    telefone: str | None = Field(default=None, max_length=40)
    endereco: str | None = Field(default=None, max_length=240)
    cidade: str | None = Field(default=None, max_length=120)
    uf: str | None = Field(default=None, min_length=2, max_length=2)
    ativa: bool = True


class LojaAtualizacao(EntradaRestrita):
    codigo: str | None = Field(default=None, min_length=1, max_length=80)
    nome: str | None = Field(default=None, min_length=1, max_length=160)
    cnpj: str | None = Field(default=None, max_length=20)
    email: EmailStr | None = None
    telefone: str | None = Field(default=None, max_length=40)
    endereco: str | None = Field(default=None, max_length=240)
    cidade: str | None = Field(default=None, max_length=120)
    uf: str | None = Field(default=None, min_length=2, max_length=2)
    ativa: bool | None = None


class UsuarioCriacao(EntradaRestrita):
    id_tipo_usuario: str | int
    id_loja: str | int | None = None
    auth_user_id: str | None = None
    nome: str = Field(min_length=1, max_length=160)
    email: EmailStr
    telefone: str | None = Field(default=None, max_length=40)
    documento: str | None = Field(default=None, max_length=40)
    ativo: bool = True


class UsuarioAtualizacao(EntradaRestrita):
    id_tipo_usuario: str | int | None = None
    id_loja: str | int | None = None
    auth_user_id: str | None = None
    nome: str | None = Field(default=None, min_length=1, max_length=160)
    email: EmailStr | None = None
    telefone: str | None = Field(default=None, max_length=40)
    documento: str | None = Field(default=None, max_length=40)
    ativo: bool | None = None


class ProdutoCriacao(EntradaRestrita):
    nome: str = Field(min_length=1, max_length=160)
    marca: str | None = Field(default=None, max_length=120)
    categoria: str | None = Field(default=None, max_length=120)
    descricao: str | None = Field(default=None, max_length=1000)
    preco_base: Decimal = Field(ge=0, decimal_places=2)
    ativo: bool = True


class ProdutoAtualizacao(EntradaRestrita):
    nome: str | None = Field(default=None, min_length=1, max_length=160)
    marca: str | None = Field(default=None, max_length=120)
    categoria: str | None = Field(default=None, max_length=120)
    descricao: str | None = Field(default=None, max_length=1000)
    preco_base: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    ativo: bool | None = None


class VariacaoProdutoCriacao(EntradaRestrita):
    id_produto: str | int
    sku: str = Field(min_length=1, max_length=120)
    cor: str = Field(min_length=1, max_length=80)
    tamanho: str = Field(min_length=1, max_length=40)
    preco_venda: Decimal = Field(ge=0, decimal_places=2)
    ativa: bool = True


class VariacaoProdutoAtualizacao(EntradaRestrita):
    id_produto: str | int | None = None
    sku: str | None = Field(default=None, min_length=1, max_length=120)
    cor: str | None = Field(default=None, min_length=1, max_length=80)
    tamanho: str | None = Field(default=None, min_length=1, max_length=40)
    preco_venda: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    ativa: bool | None = None


class OpcaoComDescricaoCriacao(EntradaRestrita):
    codigo: str = Field(min_length=1, max_length=120)
    nome: str = Field(min_length=1, max_length=160)
    descricao: str | None = Field(default=None, max_length=500)
    ativo: bool = True
    ordem: int = Field(default=0, ge=0)


class OpcaoComDescricaoAtualizacao(EntradaRestrita):
    codigo: str | None = Field(default=None, min_length=1, max_length=120)
    nome: str | None = Field(default=None, min_length=1, max_length=160)
    descricao: str | None = Field(default=None, max_length=500)
    ativo: bool | None = None
    ordem: int | None = Field(default=None, ge=0)


class OpcaoSimplesCriacao(EntradaRestrita):
    codigo: str = Field(min_length=1, max_length=120)
    nome: str = Field(min_length=1, max_length=160)
    ativo: bool = True
    ordem: int = Field(default=0, ge=0)


class OpcaoSimplesAtualizacao(EntradaRestrita):
    codigo: str | None = Field(default=None, min_length=1, max_length=120)
    nome: str | None = Field(default=None, min_length=1, max_length=160)
    ativo: bool | None = None
    ordem: int | None = Field(default=None, ge=0)


class TipoMovimentacaoCriacao(EntradaRestrita):
    codigo: str = Field(min_length=1, max_length=120)
    nome: str = Field(min_length=1, max_length=160)
    sinal: Literal[-1, 1]
    exige_pedido: bool = False
    ativo: bool = True
    ordem: int = Field(default=0, ge=0)


class TipoMovimentacaoAtualizacao(EntradaRestrita):
    codigo: str | None = Field(default=None, min_length=1, max_length=120)
    nome: str | None = Field(default=None, min_length=1, max_length=160)
    sinal: Literal[-1, 1] | None = None
    exige_pedido: bool | None = None
    ativo: bool | None = None
    ordem: int | None = Field(default=None, ge=0)


class RegistroAdminLeitura(SaidaFlexivel):
    pass
