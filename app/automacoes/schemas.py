"""Respostas e entradas das rotas das automacoes (n8n)."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.gerencia.schemas import EstoqueParado, PontosAVencer

Canal = Literal["email", "whatsapp"]


class Saida(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Vencimento(Saida):
    vence_em: datetime
    pontos: int


class ClienteAAvisar(Saida):
    id_cliente: UUID
    nome: str
    email: str | None
    telefone: str | None
    saldo: int
    categoria: str
    proxima_categoria: str | None
    faltam_para_proxima: int | None
    # So os lotes ainda nao avisados neste canal.
    pontos_a_vencer: int
    vencimentos: list[Vencimento]


class ClientesAAvisar(Saida):
    canal: Canal
    dias: int
    criterio: str
    total: int
    clientes: list[ClienteAAvisar]


class AvisoEnviado(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id_cliente: UUID
    vence_em: datetime
    pontos: int = Field(gt=0)


class AvisosEnviados(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canal: Canal
    avisos: list[AvisoEnviado] = Field(min_length=1, max_length=5000)


class AvisosGravados(Saida):
    recebidos: int
    # Avisos repetidos (mesmo cliente, lote e canal) nao contam de novo.
    gravados: int


class VendasDaLoja(Saida):
    id_loja: UUID
    loja: str
    faturamento: float
    pedidos: int
    faturamento_online: float
    faturamento_anterior: float
    pedidos_anterior: int
    # Variacao do faturamento contra a semana anterior (0.1 = +10%); nula sem base.
    variacao: float | None


class Semana(Saida):
    inicio: date
    fim: date


class ResumoSemanal(Saida):
    semana: Semana
    semana_anterior: Semana
    criterio_vendas: str
    faturamento: float
    faturamento_anterior: float
    lojas: list[VendasDaLoja]
    estoque_parado: EstoqueParado
    pontos_a_vencer: PontosAVencer | None
