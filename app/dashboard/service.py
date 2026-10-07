"""Regras do dashboard de atendimento: escopo de loja, periodos e montagem da resposta."""

from datetime import date, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.engine import Connection

from app.core.erros_auth import SemPermissao
from app.core.papeis import Papel, UsuarioAtual
from app.dashboard import repositorio
from app.dashboard.erros import PeriodoInvalido, PeriodoLongoDemais
from app.dashboard.repositorio import Filtro

PAPEIS_DO_DASHBOARD = (Papel.ATENDENTE, Papel.GERENTE_LOJA, Papel.ADMIN)
MAXIMO_DE_DIAS = 400


def resolver_loja(usuario: UsuarioAtual, id_loja_pedida: UUID | None) -> UUID | None:
    """Loja efetiva da consulta.

    Atendente e gerente so enxergam a propria loja (a do token); pedir outra e erro 403.
    Admin enxerga a rede inteira (None) ou filtra por uma loja.
    """
    if usuario.papel is Papel.ADMIN:
        return id_loja_pedida
    if usuario.id_loja is None:
        raise SemPermissao()
    if id_loja_pedida is not None and id_loja_pedida != usuario.id_loja:
        raise SemPermissao()
    return usuario.id_loja


def validar_periodo(inicio: date, fim: date) -> None:
    if fim < inicio:
        raise PeriodoInvalido()
    if (fim - inicio).days + 1 > MAXIMO_DE_DIAS:
        raise PeriodoLongoDemais()


def periodo_anterior(inicio: date, fim: date) -> tuple[date, date]:
    """Mesma duracao, imediatamente antes de `inicio`."""
    dias = (fim - inicio).days + 1
    anterior_fim = inicio - timedelta(days=1)
    return anterior_fim - timedelta(days=dias - 1), anterior_fim


def _resumo(linha: dict[str, Any]) -> dict[str, Any]:
    total = int(linha["total"])
    resolvidos = int(linha["resolvidos"])
    media = linha["resposta_media_horas"]
    return {
        "total": total,
        "resolvidos": resolvidos,
        "taxa_resolucao": resolvidos / total if total else 0.0,
        "resposta_media_horas": round(float(media), 2) if media is not None else None,
    }


def _media(valor: Any) -> float | None:
    return round(float(valor), 2) if valor is not None else None


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
    return {
        "periodo": {"inicio": inicio, "fim": fim},
        "periodo_anterior": {"inicio": ant_inicio, "fim": ant_fim},
        "atual": _resumo(repositorio.resumo(conexao, filtro, inicio, fim)),
        "anterior": _resumo(repositorio.resumo(conexao, filtro, ant_inicio, ant_fim)),
        "volume_diario": repositorio.volume_diario(conexao, filtro, inicio, fim),
        "por_categoria": repositorio.por_categoria(conexao, filtro, inicio, fim),
        "resposta_por_canal": [
            {**linha, "resposta_media_horas": _media(linha["resposta_media_horas"])}
            for linha in repositorio.resposta_por_canal(conexao, filtro, inicio, fim)
        ],
        "opcoes": {
            "lojas": repositorio.opcoes_de_loja(conexao, None if admin else usuario.id_loja),
            "canais": repositorio.opcoes_de_canal(conexao),
            "categorias": repositorio.opcoes_de_categoria(conexao),
        },
        "escopo": {
            "papel": usuario.papel.value if usuario.papel else "",
            "id_loja": usuario.id_loja,
            "pode_escolher_loja": admin,
        },
    }


def montar_fila(conexao: Connection, filtro: Filtro, *, limit: int, offset: int) -> dict[str, Any]:
    return {
        **repositorio.contadores_da_fila(conexao, filtro),
        "itens": repositorio.fila(conexao, filtro, limit=limit, offset=offset),
    }
