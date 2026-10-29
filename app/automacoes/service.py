"""Regras das automacoes: as mesmas contas do painel e do Lorenzi+, numa resposta pronta para o n8n.

Nada de LLM aqui: horario e regra fixos. O n8n so busca, monta a mensagem e devolve quem avisou.
"""

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.engine import Connection

from app.automacoes import repositorio
from app.cliente.repositorio import situacao_da_categoria
from app.cliente.vencimento_pontos import SP, pontos_a_vencer_da_base
from app.gerencia import repositorio as vendas
from app.gerencia import service as gerencia
from app.gerencia.repositorio import Filtro

CRITERIO_AVISO = (
    "Clientes ativos que aceitam mensagens, com pontos vencendo nos proximos {dias} dias e ainda "
    "nao avisados por {canal} sobre esse lote."
)
CRITERIO_VENDAS = (
    "Pedidos pagos, separados ou entregues, sem frete e sem cancelados, pela data do pedido "
    "(fuso de Sao Paulo)."
)
DIAS_PARADO = 60
PECAS_PARADAS_NO_RESUMO = 10
DIAS_DOS_PONTOS_NO_RESUMO = 30


def clientes_a_avisar(conexao: Connection, *, dias: int, canal: str) -> dict[str, Any]:
    por_cliente = pontos_a_vencer_da_base(conexao, timedelta(days=dias))
    ids = list(por_cliente)
    ja_avisados = repositorio.avisados(conexao, ids, canal)
    clientes = []
    for contato in repositorio.contatos(conexao, ids, canal):
        id_cliente = contato["id_usuario"]
        vencimentos = [
            v
            for v in por_cliente[id_cliente]["proximos_vencimentos"]
            if (id_cliente, v["vence_em"]) not in ja_avisados
        ]
        if not vencimentos:
            continue
        clientes.append(
            {
                "id_cliente": id_cliente,
                "nome": contato["nome"],
                "email": contato["email"],
                "telefone": contato["telefone"],
                "saldo": contato["saldo"],
                **situacao_da_categoria(contato["creditos_no_ano"]),
                "pontos_a_vencer": sum(v["pontos"] for v in vencimentos),
                "vencimentos": vencimentos,
            }
        )
    return {
        "canal": canal,
        "dias": dias,
        "criterio": CRITERIO_AVISO.format(dias=dias, canal=canal),
        "total": len(clientes),
        "clientes": clientes,
    }


def registrar_avisos(conexao: Connection, canal: str, avisos: list[Any]) -> dict[str, int]:
    corpo = json.dumps(
        [
            {
                "id_cliente": str(a.id_cliente),
                "vence_em": a.vence_em.isoformat(),
                "pontos": a.pontos,
            }
            for a in avisos
        ]
    )
    return {"recebidos": len(avisos), "gravados": repositorio.gravar_avisos(conexao, canal, corpo)}


def semana_fechada(hoje: date) -> tuple[date, date]:
    """A ultima semana inteira (segunda a domingo) antes de `hoje`."""
    fim = hoje - timedelta(days=hoje.weekday() + 1)
    return fim - timedelta(days=6), fim


def _variacao(atual: float, anterior: float) -> float | None:
    return round(atual / anterior - 1, 4) if anterior else None


def _vendas_da_semana(
    atual: dict[Any, dict[str, Any]], anterior: dict[Any, dict[str, Any]], nomes: dict[Any, str]
) -> list[dict[str, Any]]:
    lojas = []
    for id_loja in sorted(atual.keys() | anterior.keys(), key=lambda i: nomes.get(i, "")):
        a, b = atual.get(id_loja, {}), anterior.get(id_loja, {})
        faturamento = round(float(a.get("faturamento", 0)), 2)
        faturamento_anterior = round(float(b.get("faturamento", 0)), 2)
        lojas.append(
            {
                "id_loja": id_loja,
                "loja": nomes.get(id_loja, "loja sem cadastro"),
                "faturamento": faturamento,
                "pedidos": int(a.get("pedidos", 0)),
                "faturamento_online": round(float(a.get("faturamento_online", 0)), 2),
                "faturamento_anterior": faturamento_anterior,
                "pedidos_anterior": int(b.get("pedidos", 0)),
                "variacao": _variacao(faturamento, faturamento_anterior),
            }
        )
    return lojas


class LojaDoResumoNaoEncontrada(Exception):
    pass


def resumo_semanal(
    conexao: Connection, hoje: date | None = None, *, id_loja: UUID | None = None
) -> dict[str, Any]:
    hoje = hoje or datetime.now(UTC).astimezone(SP).date()
    inicio, fim = semana_fechada(hoje)
    inicio_ant, fim_ant = inicio - timedelta(days=7), fim - timedelta(days=7)
    escopo = Filtro(id_loja=id_loja)

    def por_loja(de: date, ate: date) -> dict[Any, dict[str, Any]]:
        return {
            linha["id_loja"]: linha for linha in vendas.vendas_por_loja(conexao, escopo, de, ate)
        }

    if id_loja is not None:
        nome_loja = repositorio.nome_da_loja_ativa(conexao, id_loja)
        if nome_loja is None:
            raise LojaDoResumoNaoEncontrada
        nomes = {id_loja: nome_loja}
    else:
        nomes = repositorio.nomes_das_lojas(conexao)

    lojas = _vendas_da_semana(por_loja(inicio, fim), por_loja(inicio_ant, fim_ant), nomes)
    if id_loja is not None and not lojas:
        lojas = _vendas_da_semana({id_loja: {}}, {}, nomes)
    estoque_parado = gerencia.montar_estoque_parado(
        conexao, escopo, dias=DIAS_PARADO, limite=PECAS_PARADAS_NO_RESUMO
    )
    return {
        "semana": {"inicio": inicio, "fim": fim},
        "semana_anterior": {"inicio": inicio_ant, "fim": fim_ant},
        "criterio_vendas": CRITERIO_VENDAS,
        "faturamento": round(sum(loja["faturamento"] for loja in lojas), 2),
        "faturamento_anterior": round(sum(loja["faturamento_anterior"] for loja in lojas), 2),
        "lojas": lojas,
        "estoque_parado": estoque_parado,
        "pontos_a_vencer": (
            gerencia.montar_pontos_a_vencer(conexao, dias=DIAS_DOS_PONTOS_NO_RESUMO)
            if id_loja is None
            else None
        ),
    }
