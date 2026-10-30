"""Respostas e entradas das rotas das automacoes (n8n)."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.gerencia.schemas import EstoqueParado, PecaParada, PontosAVencer

Canal = Literal["email", "whatsapp"]
# auto: semanal so as segundas; sim/nao forcam (por exemplo, numa demonstracao).
Semanal = Literal["auto", "sim", "nao"]


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


class CategoriaMaisVendida(Saida):
    categoria: str
    unidades: int
    faturamento: float


class IndicadoresDaUnidade(Saida):
    ticket_medio: float
    pecas_vendidas: int
    categorias_mais_vendidas: list[CategoriaMaisVendida]


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
    indicadores_unidade: IndicadoresDaUnidade | None = None
    estoque_parado: EstoqueParado
    pontos_a_vencer: PontosAVencer | None


# ---------------------------------------------------------------- estoque (operador)


class LojaComSobra(Saida):
    loja: str
    # Saldo acima do minimo daquela loja: o que da para pedir sem deixa-la abaixo do minimo.
    sobra: int


class PecaAbaixoDoMinimo(Saida):
    sku: str
    produto: str
    cor: str
    tamanho: str
    saldo: int
    minimo: int
    lojas_com_sobra: list[LojaComSobra]


class TransferenciaParada(Saida):
    id_transferencia: UUID
    tipo: str
    status: str
    # Nula: reposicao pedida a rede, sem loja de origem escolhida.
    origem: str | None
    destino: str
    sku: str
    produto: str
    cor: str
    tamanho: str
    quantidade: int
    solicitada_em: datetime
    aceita_em: datetime | None


class AjustePendente(Saida):
    id_ajuste: UUID
    sku: str
    produto: str
    cor: str
    tamanho: str
    quantidade: int
    motivo: str
    solicitante: str
    solicitado_em: datetime


class EstoqueDaLoja(Saida):
    id_loja: UUID
    loja: str
    # Falso: nada a resolver hoje (o n8n pode pular o e-mail desta loja).
    tem_pendencias: bool
    abaixo_do_minimo: list[PecaAbaixoDoMinimo]
    # Outra loja pediu pecas a esta e ninguem respondeu.
    para_responder: list[TransferenciaParada]
    # Esta loja pediu e ainda nao teve resposta.
    pedidos_sem_resposta: list[TransferenciaParada]
    # Aceitas para esta loja, sem confirmacao de recebimento.
    a_receber: list[TransferenciaParada]
    ajustes_pendentes: list[AjustePendente]


class CriteriosDoEstoque(Saida):
    abaixo_do_minimo: str
    transferencias: str
    ajustes: str


class EstoqueDoDia(Saida):
    gerado_em: datetime
    criterios: CriteriosDoEstoque
    lojas_com_pendencias: int
    lojas: list[EstoqueDaLoja]


class EstoqueParadoDaLoja(Saida):
    id_loja: UUID
    loja: str
    total_itens: int
    total_unidades: int
    total_valor: float
    # As pecas de maior valor parado (ate o limite pedido); os totais contam todas.
    itens: list[PecaParada]


class EstoqueParadoPorLoja(Saida):
    dias: int
    criterio: str
    lojas_com_estoque_parado: int
    lojas: list[EstoqueParadoDaLoja]


class EmailDeEstoque(Saida):
    tipo: Literal["diario", "semanal"]
    id_loja: UUID
    loja: str
    # Operadores de estoque ativos da loja. Vazio: a loja nao tem operador com e-mail.
    destinatarios: list[str]
    assunto: str
    html: str


class RelatoriosDeEstoque(Saida):
    data: date
    semanal: bool
    motivo_semanal: str
    total: int
    emails: list[EmailDeEstoque]
