"""Entradas e saidas do chat ao vivo do painel.

As mensagens novas chegam ao front pelo Supabase Realtime; estas saidas existem para montar a tela
(caixa de conversas, sessao do chat) e para recuperar o que se perdeu se a conexao cair.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.chamados.schemas import MensagemChamado, Opcao


class Saida(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UltimaMensagem(Saida):
    texto: str
    enviada_em: datetime
    autor: Literal["cliente", "atendente"]


class ItemConversa(Saida):
    id_atendimento: UUID
    protocolo: str
    assunto: str
    cliente_nome: str
    canal: Opcao
    prioridade: Opcao
    status: Opcao
    id_loja: UUID | None
    loja_nome: str | None
    aberto_em: datetime
    id_usuario_responsavel: UUID | None
    responsavel_nome: str | None
    sou_responsavel: bool
    nao_lidas: int
    # A ultima mensagem e do cliente: a bola esta com a equipe.
    aguardando_resposta: bool
    ultima_mensagem: UltimaMensagem | None


class ListaConversas(Saida):
    total: int
    itens: list[ItemConversa]


class ResumoConversas(Saida):
    fila: int
    minhas: int
    com_nao_lidas: int
    nao_lidas: int
    aguardando_resposta: int


class EuNoChat(Saida):
    id_usuario: UUID
    nome: str
    papel: str


class SessaoChat(Saida):
    """Tudo que o front precisa para abrir uma conversa ao vivo."""

    id_atendimento: UUID
    # Canal privado do Realtime para digitando/presenca. Mensagens vem por Postgres Changes.
    topico: str
    canal_privado: bool
    filtro_mensagens: str
    eu: EuNoChat
    status: Opcao
    id_usuario_responsavel: UUID | None
    responsavel_nome: str | None
    sou_responsavel: bool
    pode_responder: bool
    motivo_bloqueio: str | None
    ultimo_id_mensagem: UUID | None
    nao_lidas: int


class MensagensChat(Saida):
    mensagens: list[MensagemChamado]
    # Cursor para a proxima chamada (`apos`); nulo se a conversa ainda nao tem mensagem.
    ultimo_id_mensagem: UUID | None


class Lido(Saida):
    nao_lidas: int
