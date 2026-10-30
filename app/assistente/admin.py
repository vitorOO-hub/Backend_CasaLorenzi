"""Tratamento de consultas administrativas e continuidade de períodos."""

import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.assistente import periodos, service

ASSUNTO_VENDAS = re.compile(
    r"\b(vendas?|vendemos|vendeu|venderam|faturamos|faturou|faturamento|receita|"
    r"ticket medio|pedidos|pecas vendidas|mais vendid[oa]s?|marcas?|desempenho)\b"
)
PERIODO_EXPLICITO = re.compile(
    r"\b(20\d{2}|hoje|ontem|anteontem|semana|mes|mensal|ano|anual|periodo|"
    r"ultim[oa]s?|passad[oa]s?|janeiro|fevereiro|marco|abril|maio|junho|"
    r"julho|agosto|setembro|outubro|novembro|dezembro)\b|"
    r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b|\b\d{4}-\d{2}-\d{2}\b"
)
CONSULTA_SISTEMA = re.compile(
    r"\b(vendas?|vendemos|vendeu|faturamento|faturou|receita|resultado|pedidos?|"
    r"estoque|reposicao|movimentacoes?|ajustes?|transferencias?|pendencias?|"
    r"clientes?|equipe|funcionarios?|usuarios?|lojas?|unidades?|rede|"
    r"pontos?|fidelidade|chamados?|catalogo|produtos?|pecas?|marcas?|"
    r"financeiro|precos?|ticket|caixa|auditoria|integracoes?)\b"
)


def esclarecimento_necessario(pergunta: str) -> str | None:
    texto = periodos.normalizar(pergunta.strip())
    if re.search(r"\b(lucro|lucratividade|margem de lucro)\b", texto):
        return (
            "Ainda não consigo consultar o lucro: o painel não disponibiliza esse indicador. "
            "Lucro é diferente de faturamento, pois depende também dos custos e despesas. "
            "Posso consultar o faturamento da rede ou de uma loja no período desejado."
        )
    if re.search(r"\b(ganhamos|ganhou|ganho|ganhos)\b", texto) and not re.search(
        r"\b(faturamento|receita|vendas?)\b", texto
    ):
        return (
            "Você quer saber o faturamento ou o lucro? Consigo consultar o faturamento; "
            "o lucro ainda não está disponível no painel. Para consultar o faturamento, "
            "informe também o período."
        )
    consultas_sem_periodo = re.search(
        r"\b(pendentes?|pendencias?|cliente|clientes|catalogo|estoque|reposicao)\b", texto
    )
    if (
        ASSUNTO_VENDAS.search(texto)
        and not PERIODO_EXPLICITO.search(texto)
        and not consultas_sem_periodo
    ):
        return periodos.PEDIDO_PERIODO
    return None


def contextualizar_periodo(pergunta: str, historico: list[dict[str, Any]]) -> str:
    return periodos.contextualizar(
        pergunta,
        historico,
        aceitar_assunto=lambda texto: bool(ASSUNTO_VENDAS.search(periodos.normalizar(texto))),
    )


def exige_ferramenta(pergunta: str) -> bool:
    return bool(CONSULTA_SISTEMA.search(periodos.normalizar(pergunta)))


def enviar_mensagem(executar_db, usuario, configuracoes, id_conversa, pergunta):
    hoje = datetime.now(ZoneInfo("America/Sao_Paulo")).date().isoformat()
    instrucoes = (
        service.INSTRUCOES + f"\nData atual em São Paulo: {hoje}. "
        "Use esta data como referência para períodos relativos."
    )
    return service.enviar_mensagem(
        executar_db, usuario, configuracoes, id_conversa, pergunta,
        instrucoes=instrucoes,
        esclarecer=esclarecimento_necessario,
        contextualizar=contextualizar_periodo,
        forcar_ferramenta=exige_ferramenta,
    )
