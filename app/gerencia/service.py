"""Regras do inicio do gerente: escopo de loja, periodos e montagem das respostas."""

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy.engine import Connection

from app.core.erros_auth import SemPermissao
from app.core.papeis import Papel, UsuarioAtual
from app.dashboard import repositorio as repositorio_de_chamados
from app.dashboard.repositorio import Filtro as FiltroDeChamados
from app.dashboard.service import periodo_anterior, resolver_loja, validar_periodo
from app.gerencia import repositorio
from app.gerencia.repositorio import CANAIS_DE_VENDA, Filtro

PAPEIS_DA_GERENCIA = (Papel.GERENTE_LOJA, Papel.ADMIN)
PECAS_NO_RANKING = 6

__all__ = ["PAPEIS_DA_GERENCIA", "loja_do_escopo", "validar_periodo"]


def loja_do_escopo(usuario: UsuarioAtual, id_loja_pedida: UUID | None) -> UUID | None:
    """Gerente so enxerga a propria loja (a do token); o admin escolhe uma ou ve a rede."""
    if usuario.papel not in PAPEIS_DA_GERENCIA:
        raise SemPermissao()
    return resolver_loja(usuario, id_loja_pedida)


def _dinheiro(valor: Any) -> float:
    return round(float(valor), 2)


def _resumo(linha: dict[str, Any]) -> dict[str, Any]:
    faturamento = _dinheiro(linha["faturamento"])
    pedidos = int(linha["pedidos"])
    online = _dinheiro(linha["faturamento_online"])
    return {
        "faturamento": faturamento,
        "pedidos": pedidos,
        "pecas": int(linha["pecas"]),
        "ticket_medio": round(faturamento / pedidos, 2) if pedidos else 0.0,
        "faturamento_online": online,
        "pedidos_online": int(linha["pedidos_online"]),
        "participacao_online": round(online / faturamento, 4) if faturamento else 0.0,
    }


def montar_dashboard(
    conexao: Connection,
    usuario: UsuarioAtual,
    *,
    inicio: date,
    fim: date,
    filtro: Filtro,
) -> dict[str, Any]:
    ant_inicio, ant_fim = periodo_anterior(inicio, fim)
    admin = usuario.papel is Papel.ADMIN
    loja = repositorio.loja_por_id(conexao, filtro.id_loja) if filtro.id_loja else None
    lojas = repositorio_de_chamados.opcoes_de_loja(conexao, None if admin else usuario.id_loja)
    return {
        "periodo": {"inicio": inicio, "fim": fim},
        "periodo_anterior": {"inicio": ant_inicio, "fim": ant_fim},
        "atual": _resumo(repositorio.resumo(conexao, filtro, inicio, fim)),
        "anterior": _resumo(repositorio.resumo(conexao, filtro, ant_inicio, ant_fim)),
        "serie_diaria": [
            {
                "data": linha["data"],
                "faturamento": _dinheiro(linha["faturamento"]),
                "pedidos": int(linha["pedidos"]),
                "pecas": int(linha["pecas"]),
            }
            for linha in repositorio.serie_diaria(conexao, filtro, inicio, fim)
        ],
        "movimento_semana": [
            {
                "dia_semana": int(linha["dia_semana"]),
                "pedidos": int(linha["pedidos"]),
                "dias": int(linha["dias"]),
                "pedidos_por_dia": (
                    round(int(linha["pedidos"]) / int(linha["dias"]), 2) if linha["dias"] else 0.0
                ),
            }
            for linha in repositorio.movimento_semana(conexao, filtro, inicio, fim)
        ],
        "pecas_mais_vendidas": [
            {
                **linha,
                "unidades": int(linha["unidades"]),
                "faturamento": _dinheiro(linha["faturamento"]),
            }
            for linha in repositorio.pecas_mais_vendidas(
                conexao, filtro, inicio, fim, limite=PECAS_NO_RANKING
            )
        ],
        "opcoes": {
            "lojas": lojas,
            "canais": [{"codigo": c, "nome": n} for c, n in CANAIS_DE_VENDA],
            "categorias": repositorio.categorias_de_produto(conexao),
        },
        "escopo": {
            "papel": usuario.papel.value if usuario.papel else "",
            "id_loja": usuario.id_loja,
            "loja_nome": loja["nome"] if loja else None,
            "pode_escolher_loja": admin,
        },
    }


def montar_reposicao(conexao: Connection, filtro: Filtro, *, limite: int) -> dict[str, Any]:
    total, itens = repositorio.reposicao(conexao, filtro, limite=limite)
    return {
        "total": total,
        "itens": [
            {
                **item,
                "giro_diario": (
                    round(float(item["giro_diario"]), 3)
                    if item["giro_diario"] is not None
                    else None
                ),
                "dias_cobertura": (
                    round(float(item["dias_cobertura"]), 1)
                    if item["dias_cobertura"] is not None
                    else None
                ),
            }
            for item in itens
        ],
    }


def montar_lojas(conexao: Connection, filtro: Filtro) -> dict[str, Any]:
    """O gerente ve so a propria loja; o admin, a rede. O escopo vem do filtro (do token)."""
    return {
        "itens": [
            {
                **linha,
                "equipe": int(linha["equipe"]),
                "unidades_em_estoque": int(linha["unidades_em_estoque"]),
                "pecas_em_alerta": int(linha["pecas_em_alerta"]),
                "vendas_30_dias": _dinheiro(linha["vendas_30_dias"]),
                "chamados_abertos": int(linha["chamados_abertos"]),
            }
            for linha in repositorio.lojas_da_rede(conexao, filtro.id_loja)
        ]
    }


def montar_pendencias(
    conexao: Connection, filtro: Filtro, *, incluir_chamados_sem_loja: bool
) -> dict[str, int]:
    ajustes = repositorio.ajustes_para_aprovar(conexao, filtro)
    transferencias = repositorio.transferencias_aguardando(conexao, filtro)
    chamados = repositorio_de_chamados.contadores_da_fila(
        conexao,
        FiltroDeChamados(filtro.id_loja, incluir_sem_loja=incluir_chamados_sem_loja),
    )["sem_resposta"]
    return {
        "ajustes_para_aprovar": int(ajustes),
        "transferencias_aguardando": int(transferencias),
        "chamados_sem_resposta": int(chamados),
        "total": int(ajustes) + int(transferencias) + int(chamados),
    }
