"""Respostas do saldo e do historico de movimentacoes do painel de estoque."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class Saida(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LojaOpcao(Saida):
    id_loja: UUID
    nome: str


class Opcao(Saida):
    codigo: str
    nome: str


class PecaOpcao(Saida):
    id_variacao: UUID
    sku: str
    nome: str


class Escopo(Saida):
    papel: str
    id_loja: UUID | None
    loja_nome: str | None
    pode_escolher_loja: bool
    # O operador de estoque so enxerga as movimentacoes que ele mesmo registrou.
    somente_minhas: bool


class Opcoes(Saida):
    lojas: list[LojaOpcao]
    # Todas as lojas ativas da rede (para escolher de onde pedir pecas), so id e nome.
    rede: list[LojaOpcao]
    categorias: list[str]
    situacoes: list[Opcao]
    tipos: list[Opcao]
    pecas: list[PecaOpcao]
    motivos_entrada: list[str]
    motivos_saida: list[str]
    escopo: Escopo


class SaldoNaLoja(Saida):
    id_loja: UUID
    quantidade: int
    minimo: int


class ItemSaldo(Saida):
    id_variacao: UUID
    sku: str
    produto: str
    cor: str
    tamanho: str
    categoria: str | None
    preco: float
    # Soma das lojas visiveis e dos minimos delas.
    total: int
    minimo_total: int
    # ok | baixo | esgotado
    situacao: str
    por_loja: list[SaldoNaLoja]


class ResumoSaldo(Saida):
    unidades: int
    pecas: int
    estoque_baixo: int
    esgotadas: int
    # Unidades a preco de venda.
    valor_em_estoque: float


class Saldo(Saida):
    resumo: ResumoSaldo
    lojas: list[LojaOpcao]
    total: int
    itens: list[ItemSaldo]


class ItemMovimentacao(Saida):
    id_movimentacao: UUID
    data: datetime
    id_loja: UUID
    loja_nome: str
    id_variacao: UUID
    sku: str
    produto: str
    cor: str
    tamanho: str
    tipo_codigo: str
    tipo_nome: str
    # entrada | saida | ajuste | transferencia
    grupo: str
    # Com sinal: entrada positiva, saida negativa.
    quantidade: int
    quantidade_anterior: int
    quantidade_posterior: int
    responsavel: str | None
    motivo: str | None
    numero_pedido: str | None


class Movimentacoes(Saida):
    total: int
    itens: list[ItemMovimentacao]


class ItemAjuste(Saida):
    id_ajuste: UUID
    id_loja: UUID
    loja_nome: str
    id_variacao: UUID
    sku: str
    produto: str
    cor: str
    tamanho: str
    # Diferenca a aplicar ao saldo (positiva soma, negativa tira).
    quantidade: int
    saldo_atual: int
    motivo: str
    # pendente | aprovado | rejeitado
    status: str
    motivo_recusa: str | None
    solicitante: str
    decisor: str | None
    solicitado_em: datetime
    decidido_em: datetime | None


class Ajustes(Saida):
    total: int
    # Quantos ajustes pendentes existem no escopo, independente do filtro da lista.
    pendentes: int
    itens: list[ItemAjuste]
