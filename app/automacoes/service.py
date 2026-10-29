"""Regras das automacoes: as mesmas contas do painel e do Lorenzi+, numa resposta pronta para o n8n.

Nada de LLM aqui: horario e regra fixos. O n8n so busca, monta a mensagem e devolve quem avisou.
"""

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.engine import Connection

from app.automacoes import emails_estoque, repositorio
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
CRITERIO_MINIMO = (
    "Pecas ativas com saldo igual ou abaixo do estoque minimo definido pela loja (so onde ha "
    "minimo). Lojas com sobra: ate 3 outras lojas ativas com saldo acima do minimo delas."
)
CRITERIO_TRANSFERENCIAS = (
    "Transferencias solicitadas sem resposta ha mais de {horas} horas e aceitas (em transito) "
    "sem confirmacao de recebimento ha mais de {dias} dias."
)
CRITERIO_SO_FISICAS = " So lojas fisicas (com horario de atendimento cadastrado)."
CRITERIO_AJUSTES = "Ajustes de inventario ainda pendentes de aprovacao, de qualquer data."


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


# ---------------------------------------------------------------- estoque (operador)


def _transferencia(linha: dict[str, Any]) -> dict[str, Any]:
    return {
        k: linha[k]
        for k in (
            "id_transferencia",
            "tipo",
            "status",
            "origem",
            "destino",
            "sku",
            "produto",
            "cor",
            "tamanho",
            "quantidade",
            "solicitada_em",
            "aceita_em",
        )
    }


def estoque_do_dia(conexao: Connection, *, horas: int, dias: int) -> dict[str, Any]:
    """O que cada loja precisa resolver hoje: reposicao e pendencias paradas.

    Uma transferencia aparece para a loja que precisa agir (origem responde, destino confirma o
    recebimento) e, quando ninguem respondeu, tambem para quem pediu.
    """
    lojas = {
        loja["id_loja"]: {
            "id_loja": loja["id_loja"],
            "loja": loja["nome"],
            "abaixo_do_minimo": [],
            "para_responder": [],
            "pedidos_sem_resposta": [],
            "a_receber": [],
            "ajustes_pendentes": [],
        }
        for loja in repositorio.lojas_ativas(conexao)
    }
    for peca in repositorio.abaixo_do_minimo(conexao):
        if peca["id_loja"] in lojas:
            lojas[peca["id_loja"]]["abaixo_do_minimo"].append(
                {k: v for k, v in peca.items() if k != "id_loja"}
            )
    for linha in repositorio.transferencias_paradas(conexao, horas=horas, dias=dias):
        destino = lojas.get(linha["id_loja_destino"])
        if linha["status"] == "aceita":
            if destino:
                destino["a_receber"].append(_transferencia(linha))
            continue
        origem = lojas.get(linha["id_loja_origem"])
        if origem:
            origem["para_responder"].append(_transferencia(linha))
        if destino:
            destino["pedidos_sem_resposta"].append(_transferencia(linha))
    for ajuste in repositorio.ajustes_pendentes(conexao):
        if ajuste["id_loja"] in lojas:
            lojas[ajuste["id_loja"]]["ajustes_pendentes"].append(
                {k: v for k, v in ajuste.items() if k != "id_loja"}
            )
    listas = (
        "abaixo_do_minimo",
        "para_responder",
        "pedidos_sem_resposta",
        "a_receber",
        "ajustes_pendentes",
    )
    resultado = [
        {**loja, "tem_pendencias": any(loja[nome] for nome in listas)} for loja in lojas.values()
    ]
    return {
        "gerado_em": datetime.now(UTC),
        "criterios": {
            "abaixo_do_minimo": CRITERIO_MINIMO,
            "transferencias": CRITERIO_TRANSFERENCIAS.format(horas=horas, dias=dias),
            "ajustes": CRITERIO_AJUSTES,
        },
        "lojas_com_pendencias": sum(1 for loja in resultado if loja["tem_pendencias"]),
        "lojas": resultado,
    }


def estoque_parado_por_loja(conexao: Connection, *, dias: int, limite: int) -> dict[str, Any]:
    """A mesma conta do painel da gerencia, loja a loja (cada loja recebe a sua lista). So lojas
    fisicas: no CD e no e-commerce, peca guardada por meses e o normal, nao um alerta."""
    lojas = []
    for loja in repositorio.lojas_ativas(conexao, so_fisicas=True):
        parado = gerencia.montar_estoque_parado(
            conexao, Filtro(id_loja=loja["id_loja"]), dias=dias, limite=limite
        )
        lojas.append(
            {
                "id_loja": loja["id_loja"],
                "loja": loja["nome"],
                "total_itens": parado["total_itens"],
                "total_unidades": parado["total_unidades"],
                "total_valor": parado["total_valor"],
                "itens": parado["itens"],
            }
        )
    return {
        "dias": dias,
        "criterio": gerencia.CRITERIO_PARADO.format(dias=dias) + CRITERIO_SO_FISICAS,
        "lojas_com_estoque_parado": sum(1 for loja in lojas if loja["total_itens"]),
        "lojas": lojas,
    }


SEGUNDA = 0
MOTIVO_SEMANAL = {
    "auto_sim": "segunda-feira: o relatorio semanal vai junto com o diario",
    "auto_nao": "o relatorio semanal so sai as segundas-feiras",
    "sim": "relatorio semanal pedido para hoje (fora da segunda)",
    "nao": "relatorio semanal desligado neste envio",
}


def relatorios_estoque(
    conexao: Connection,
    *,
    semanal: str,
    painel_url: str,
    horas: int,
    dias: int,
    dias_parado: int,
    limite: int,
    hoje: date | None = None,
) -> dict[str, Any]:
    """Os e-mails do dia para os operadores de estoque, ja prontos (o n8n so envia).

    O diario sai todo dia, para cada loja com algo a resolver. O semanal (estoque parado) sai as
    segundas; `semanal` = "sim" ou "nao" forca o envio ou o corte (por exemplo, numa demonstracao).
    """
    hoje = hoje or datetime.now(UTC).astimezone(SP).date()
    if semanal == "auto":
        incluir = hoje.weekday() == SEGUNDA
        motivo = MOTIVO_SEMANAL["auto_sim" if incluir else "auto_nao"]
    else:
        incluir = semanal == "sim"
        motivo = MOTIVO_SEMANAL[semanal]
    operadores = repositorio.operadores_de_estoque(conexao)

    def email(tipo: str, loja: dict[str, Any], conteudo: dict[str, str]) -> dict[str, Any]:
        return {
            "tipo": tipo,
            "id_loja": loja["id_loja"],
            "loja": loja["loja"],
            "destinatarios": operadores.get(loja["id_loja"], []),
            **conteudo,
        }

    do_dia = estoque_do_dia(conexao, horas=horas, dias=dias)
    emails = [
        email(
            "diario",
            loja,
            emails_estoque.diario(loja, do_dia["criterios"], hoje, painel_url, limite),
        )
        for loja in do_dia["lojas"]
        if loja["tem_pendencias"]
    ]
    if incluir:
        parado = estoque_parado_por_loja(conexao, dias=dias_parado, limite=limite)
        emails += [
            email(
                "semanal",
                loja,
                emails_estoque.semanal(loja, parado["dias"], parado["criterio"], hoje, painel_url),
            )
            for loja in parado["lojas"]
            if loja["total_itens"]
        ]
    return {
        "data": hoje,
        "semanal": incluir,
        "motivo_semanal": motivo,
        "total": len(emails),
        "emails": emails,
    }
