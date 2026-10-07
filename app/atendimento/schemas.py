"""Schemas do modulo de atendimento."""

from pydantic import BaseModel, ConfigDict, Field


class EntradaRestrita(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SaidaFlexivel(BaseModel):
    model_config = ConfigDict(extra="allow")


class AtendimentoCriacao(EntradaRestrita):
    id_cliente: str | int
    id_usuario_responsavel: str | int | None = None
    id_pedido: str | int | None = None
    id_canal_atendimento: str | int
    id_categoria_atendimento: str | int
    id_prioridade_atendimento: str | int
    id_status_atendimento: str | int


class AtendimentoAtualizacao(EntradaRestrita):
    id_usuario_responsavel: str | int | None = None
    id_pedido: str | int | None = None
    id_canal_atendimento: str | int | None = None
    id_categoria_atendimento: str | int | None = None
    id_prioridade_atendimento: str | int | None = None
    id_status_atendimento: str | int | None = None
    encerrado_em: str | None = None


class StatusAtendimentoAtualizacao(EntradaRestrita):
    id_status_atendimento: str | int
    encerrado_em: str | None = None


class ResponsavelAtendimentoAtualizacao(EntradaRestrita):
    id_usuario_responsavel: str | int | None


class AtendimentoItemCriacao(EntradaRestrita):
    id_item_pedido: str | int


class MensagemCriacao(EntradaRestrita):
    id_usuario_remetente: str | int
    texto: str = Field(min_length=1, max_length=5000)
    anexo_url: str | None = Field(default=None, max_length=1000)


class AvaliacaoAtendimentoCriacao(EntradaRestrita):
    nota: int = Field(ge=1, le=5)
    comentario: str | None = Field(default=None, max_length=1000)


class RegistroAtendimentoLeitura(SaidaFlexivel):
    pass
