"""Respostas do inicio do gerente. Nunca expoem dados pessoais de cliente (so totais e produtos)."""

from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class Saida(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Periodo(Saida):
    inicio: date
    fim: date


class ResumoVendas(Saida):
    # Faturamento de produtos: soma dos itens dos pedidos pagos, sem o frete.
    faturamento: float
    pedidos: int
    pecas: int
    ticket_medio: float
    faturamento_online: float
    pedidos_online: int
    # Parte do faturamento que veio do online (0 a 1).
    participacao_online: float


class VendaDia(Saida):
    data: date
    faturamento: float
    pedidos: int
    pecas: int


class MovimentoDiaSemana(Saida):
    # 0 = domingo ... 6 = sabado (mesma convencao do JavaScript).
    dia_semana: int
    pedidos: int
    # Quantos dias desse tipo existem no periodo (divisor da media).
    dias: int
    pedidos_por_dia: float


class PecaMaisVendida(Saida):
    id_produto: UUID
    nome: str
    categoria: str | None
    unidades: int
    faturamento: float


class Opcao(Saida):
    codigo: str
    nome: str


class LojaOpcao(Saida):
    id_loja: UUID
    nome: str


class Escopo(Saida):
    papel: str
    id_loja: UUID | None
    loja_nome: str | None
    pode_escolher_loja: bool


class Opcoes(Saida):
    lojas: list[LojaOpcao]
    canais: list[Opcao]
    categorias: list[str]


class DashboardGerente(Saida):
    periodo: Periodo
    periodo_anterior: Periodo
    atual: ResumoVendas
    anterior: ResumoVendas
    serie_diaria: list[VendaDia]
    movimento_semana: list[MovimentoDiaSemana]
    pecas_mais_vendidas: list[PecaMaisVendida]
    opcoes: Opcoes
    escopo: Escopo


class ItemReposicao(Saida):
    id_variacao: UUID
    sku: str
    produto: str
    cor: str
    tamanho: str
    categoria: str | None
    saldo: int
    minimo: int
    # Venda media por dia nos ultimos 30 dias; nula se a peca nao vendeu.
    giro_diario: float | None
    # Saldo dividido pelo giro. Nulo quando nao ha giro.
    dias_cobertura: float | None
    # esgotada | abaixo_do_minimo | cobertura_curta
    situacao: str


class Reposicao(Saida):
    total: int
    itens: list[ItemReposicao]


class Pendencias(Saida):
    ajustes_para_aprovar: int
    transferencias_aguardando: int
    chamados_sem_resposta: int
    total: int
