"""Entradas e saidas da area de chamados do painel.

Nenhuma entrada aceita remetente, papel ou loja: esses valores vem do token. Campos
desconhecidos viram 422 (extra="forbid").
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Saida(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MensagemCriar(Entrada):
    texto: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class Opcao(Saida):
    codigo: str
    nome: str


class LojaOpcao(Saida):
    id_loja: UUID
    nome: str


class OpcoesChamados(Saida):
    status: list[Opcao]
    canais: list[Opcao]
    categorias: list[Opcao]
    prioridades: list[Opcao]
    lojas: list[LojaOpcao]


class ResumoChamados(Saida):
    sem_resposta: int
    em_andamento: int
    prioridade_alta: int
    resolvidos: int
    na_fila: int = Field(description="Abertos sem responsavel")
    meus: int = Field(description="Abertos que o usuario logado assumiu")


class ItemChamado(Saida):
    id_atendimento: UUID
    protocolo: str
    assunto: str
    cliente_nome: str
    categoria: Opcao
    canal: Opcao
    prioridade: Opcao
    status: Opcao
    id_loja: UUID | None
    loja_nome: str | None
    aberto_em: datetime
    id_usuario_responsavel: UUID | None
    responsavel_nome: str | None
    sou_responsavel: bool


class ListaChamados(Saida):
    total: int
    itens: list[ItemChamado]


class ClienteChamado(Saida):
    id_cliente: UUID
    nome: str
    email: str
    telefone: str | None
    cidade: str | None
    cliente_desde: datetime


class PedidoChamado(Saida):
    id_pedido: UUID
    numero_pedido: str
    status: str


class PecaChamado(Saida):
    nome: str
    sku: str
    cor: str
    tamanho: str


class AnexoChamado(Saida):
    id_anexo: UUID
    nome: str
    caminho: str
    criado_em: datetime


class OutroChamado(Saida):
    id_atendimento: UUID
    protocolo: str
    assunto: str
    status: Opcao


class CompraRecente(Saida):
    id_pedido: UUID
    numero_pedido: str
    criado_em: datetime
    valor_total: Decimal


class DetalheChamado(ItemChamado):
    cliente: ClienteChamado
    pedido: PedidoChamado | None
    pecas: list[PecaChamado]
    anexos: list[AnexoChamado]
    outros_chamados: list[OutroChamado]
    # So gerente e admin; para o atendente a lista vem nula, e nao vazia.
    compras_recentes: list[CompraRecente] | None


class MensagemChamado(Saida):
    id_mensagem: UUID
    autor: Literal["cliente", "atendente"]
    nome: str
    texto: str
    enviada_em: datetime
