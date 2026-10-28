"""Contratos HTTP do assistente administrativo."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NovaConversa(Entrada):
    titulo: str | None = Field(default=None, max_length=100)


class Mensagem(Entrada):
    texto: str = Field(min_length=1, max_length=2000)


class Conversa(BaseModel):
    id_conversa: UUID
    titulo: str | None
    criada_em: datetime
    atualizada_em: datetime


class ItemMensagem(BaseModel):
    autor: str
    texto: str
    criada_em: datetime
    modelo: str | None = None


class HistoricoConversa(Conversa):
    mensagens: list[ItemMensagem]


class RespostaAssistente(BaseModel):
    id_conversa: UUID
    resposta: str
    provedor: str | None = None
    modelo: str | None = None
