"""Saidas da area de clientes do painel.

Nunca incluem documento (CPF). E-mail e telefone aparecem porque o atendimento precisa falar com o
cliente. Compras e valores so existem para gerente e admin: para o atendente os campos vem nulos.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.chamados.schemas import Opcao


class Saida(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ItemCliente(Saida):
    id_cliente: UUID
    nome: str
    email: str | None
    telefone: str | None
    cidade: str | None
    cliente_desde: datetime
    total_chamados: int
    chamados_em_aberto: int
    compras: int | None
    total_gasto: Decimal | None


class ListaClientes(Saida):
    total: int
    itens: list[ItemCliente]


class ResumoCliente(Saida):
    chamados: int
    chamados_em_aberto: int
    compras: int | None
    total_gasto: Decimal | None
    ticket_medio: Decimal | None


class DadosCliente(Saida):
    id_cliente: UUID
    nome: str
    email: str | None
    telefone: str | None
    cidade: str | None
    cliente_desde: datetime


class ChamadoDoCliente(Saida):
    id_atendimento: UUID
    protocolo: str
    assunto: str
    categoria: Opcao
    status: Opcao
    aberto_em: datetime
    # Atendimento importado do historico da Vulto (fora das filas da equipe).
    historico_vulto: bool = False


class CompraDoCliente(Saida):
    id_pedido: UUID
    numero_pedido: str
    criado_em: datetime
    loja_nome: str
    valor_total: Decimal
    status: Opcao


class FichaCliente(Saida):
    cliente: DadosCliente
    resumo: ResumoCliente
    chamados: list[ChamadoDoCliente]
    # So gerente e admin; para o atendente vem nulo (e nem chega a ser consultado).
    compras: list[CompraDoCliente] | None


class MovimentoPontosFicha(Saida):
    ocorrido_em: datetime
    tipo: str
    pontos: int
    descricao: str


class ResgateFicha(Saida):
    resgatado_em: datetime
    pontos: int
    # Valor em reais: so gerente e admin (como as compras); para o atendente vem nulo.
    desconto: Decimal | None
    loja_nome: str | None
    atendente: str | None
    observacao: str | None


class VultoMaisDaFicha(Saida):
    """Programa de pontos Vulto+ do cliente, visto pela equipe."""

    saldo: int
    categoria: str
    creditos_no_ano: int
    proxima_categoria: str | None
    faltam_para_proxima: int | None
    loja_cadastro: str | None
    extrato: list[MovimentoPontosFicha]
    resgates: list[ResgateFicha]
