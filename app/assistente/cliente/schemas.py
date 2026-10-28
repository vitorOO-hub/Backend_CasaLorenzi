"""Schemas das rotas do assistente do cliente."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints


class MensagemCriacao(BaseModel):
    model_config = ConfigDict(extra="forbid")

    texto: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class MensagemConversa(BaseModel):
    autor: Literal["usuario", "assistente"]
    texto: str
    criada_em: datetime


class Conversa(BaseModel):
    id_conversa: UUID
    status: Literal["ativa", "com_atendente", "encerrada"]
    id_atendimento: UUID | None = None
    criada_em: datetime
    mensagens: list[MensagemConversa]


class RespostaAssistente(BaseModel):
    id_conversa: UUID
    status: Literal["ativa", "com_atendente"]
    resposta: str
    # True quando nao houve resposta confiavel (fica marcada para a equipe revisar).
    sem_resposta: bool
    # O front recarrega a sacola quando o assistente colocou uma peca nela.
    carrinho_alterado: bool
    # Chamado aberto pela transferencia para atendente.
    id_atendimento: UUID | None = None
