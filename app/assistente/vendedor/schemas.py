"""Entradas e respostas do chat do assistente."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints

TAMANHO_MAXIMO_PERGUNTA = 1000


class Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Saida(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NovaMensagem(Entrada):
    texto: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=TAMANHO_MAXIMO_PERGUNTA),
    ]


class AlteracaoDaConversa(Entrada):
    # Arquivar tira a conversa da lista; desarquivar a traz de volta.
    arquivada: bool


class Conversa(Saida):
    id_conversa: UUID
    titulo: str
    status: Literal["ativa", "com_atendente", "encerrada"]
    criada_em: datetime
    atualizada_em: datetime


class ListaDeConversas(Saida):
    itens: list[Conversa]


class MensagemDoChat(Saida):
    id_mensagem: UUID
    autor: Literal["usuario", "assistente"]
    texto: str
    criada_em: datetime
    # Ferramentas consultadas para montar a resposta (nomes), para a tela mostrar.
    ferramentas: list[str] = []


class MensagensDaConversa(Saida):
    conversa: Conversa
    mensagens: list[MensagemDoChat]


class RespostaDoAssistente(Saida):
    pergunta: MensagemDoChat
    resposta: MensagemDoChat
