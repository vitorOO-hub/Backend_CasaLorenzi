"""Respostas do dashboard de atendimento. Nunca expoem e-mail, telefone nem documento."""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class Saida(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Resumo(Saida):
    total: int
    resolvidos: int
    taxa_resolucao: float
    resposta_media_horas: float | None


class Periodo(Saida):
    inicio: date
    fim: date


class VolumeDia(Saida):
    data: date
    total: int


class PorCategoria(Saida):
    codigo: str
    nome: str
    total: int


class RespostaPorCanal(Saida):
    codigo: str
    nome: str
    total: int
    resposta_media_horas: float | None


class Opcao(Saida):
    codigo: str
    nome: str


class LojaOpcao(Saida):
    id_loja: UUID
    nome: str


class Escopo(Saida):
    papel: str
    id_loja: UUID | None
    pode_escolher_loja: bool


class Opcoes(Saida):
    lojas: list[LojaOpcao]
    canais: list[Opcao]
    categorias: list[Opcao]


class DashboardAtendimento(Saida):
    periodo: Periodo
    periodo_anterior: Periodo
    atual: Resumo
    anterior: Resumo
    volume_diario: list[VolumeDia]
    por_categoria: list[PorCategoria]
    resposta_por_canal: list[RespostaPorCanal]
    opcoes: Opcoes
    escopo: Escopo


class ItemFila(Saida):
    id_atendimento: UUID
    assunto: str
    cliente_nome: str
    canal_codigo: str
    canal: str
    categoria_codigo: str
    categoria: str
    prioridade_codigo: str
    prioridade: str
    status_codigo: str
    status: str
    aberto_em: datetime
    id_loja: UUID | None
    loja_nome: str | None
    sem_resposta: bool


class FilaAtendimento(Saida):
    total_aberto: int
    sem_resposta: int
    urgentes: int
    itens: list[ItemFila]
