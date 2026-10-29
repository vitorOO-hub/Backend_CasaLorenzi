"""Schemas das rotas do assistente do cliente."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints


class MensagemCriacao(BaseModel):
    model_config = ConfigDict(extra="forbid")

    texto: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class VariacaoOferta(BaseModel):
    id_variacao: UUID
    sku: str
    cor: str
    tamanho: str
    preco: Decimal


class Oferta(BaseModel):
    """Cartao da peca no chat: o botao "Adicionar a sacola" usa `id_variacao` e `quantidade`."""

    id_variacao: UUID
    sku: str
    produto: str
    # Sem foto, o cartao mostra o quadro da marca (como o catalogo: "Vulto · foto em breve").
    marca: str | None = None
    cor: str
    tamanho: str
    preco: Decimal
    imagem_url: str | None = None
    imagem_alt: str | None = None
    tecido: str | None = None
    quantidade: int = 1
    # Cor e tamanho em estoque para escolher no cartao (peca exata: uma so).
    variacoes: list[VariacaoOferta] = []


Avaliacao = Literal["util", "nao_util"]


class MensagemConversa(BaseModel):
    id_mensagem: UUID | None = None
    avaliacao: Avaliacao | None = None
    autor: Literal["usuario", "assistente"]
    texto: str
    criada_em: datetime
    ofertas: list[Oferta] = []


class Conversa(BaseModel):
    id_conversa: UUID
    status: Literal["ativa", "com_atendente", "encerrada"]
    id_atendimento: UUID | None = None
    criada_em: datetime
    mensagens: list[MensagemConversa]


class RespostaAssistente(BaseModel):
    id_conversa: UUID
    id_mensagem: UUID | None = None
    status: Literal["ativa", "com_atendente"]
    resposta: str
    # True quando nao houve resposta confiavel (fica marcada para a equipe revisar).
    sem_resposta: bool
    # Sempre False: o assistente nao mexe mais na sacola (mantido para o front anterior).
    carrinho_alterado: bool = False
    # Pecas mostradas com o botao "Adicionar a sacola"; quem coloca na sacola e o cliente.
    ofertas: list[Oferta] = []
    # Chamado aberto pela transferencia para atendente.
    id_atendimento: UUID | None = None


class ConversaResumo(BaseModel):
    """Item do historico lateral do chat."""

    id_conversa: UUID
    status: Literal["ativa", "com_atendente", "encerrada"]
    id_atendimento: UUID | None = None
    titulo: str
    criada_em: datetime
    atualizada_em: datetime


class AlteracaoDaConversa(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arquivada: bool


class AvaliacaoDaResposta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # null tira a avaliacao.
    avaliacao: Avaliacao | None
