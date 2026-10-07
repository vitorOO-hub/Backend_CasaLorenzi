"""Regras do saldo e do historico de movimentacoes do painel de estoque."""

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy.engine import Connection

from app.chamados.repositorio import id_usuario_ativo
from app.core.erros_auth import SemPermissao
from app.core.papeis import Papel, UsuarioAtual
from app.dashboard.erros import PeriodoInvalido
from app.dashboard.service import resolver_loja
from app.painel_estoque import repositorio
from app.painel_estoque.repositorio import FiltroMovimentacoes, FiltroSaldo

PAPEIS_DO_ESTOQUE = (Papel.OPERADOR_ESTOQUE, Papel.GERENTE_LOJA, Papel.ADMIN)
MOTIVOS_ENTRADA = ["Recebimento de fornecedor", "Devolução de cliente"]
MOTIVOS_SAIDA = ["Venda em loja", "Avaria", "Peça para ajuste no ateliê"]


def loja_do_escopo(usuario: UsuarioAtual, id_loja_pedida: UUID | None) -> UUID | None:
    """Operador e gerente so enxergam a propria loja (a do token); o admin escolhe ou ve a rede."""
    if usuario.papel not in PAPEIS_DO_ESTOQUE:
        raise SemPermissao()
    return resolver_loja(usuario, id_loja_pedida)


def somente_minhas(usuario: UsuarioAtual) -> bool:
    return usuario.papel is Papel.OPERADOR_ESTOQUE


def montar_opcoes(
    conexao: Connection, usuario: UsuarioAtual, id_loja: UUID | None
) -> dict[str, Any]:
    admin = usuario.papel is Papel.ADMIN
    loja = repositorio.loja_por_id(conexao, id_loja) if id_loja else None
    return {
        "lojas": repositorio.lojas_visiveis(conexao, None if admin else usuario.id_loja),
        "rede": repositorio.lojas_visiveis(conexao, None),
        "categorias": repositorio.categorias(conexao, id_loja),
        "situacoes": [{"codigo": c, "nome": n} for c, n in repositorio.SITUACOES],
        "tipos": [{"codigo": c, "nome": n} for c, n in repositorio.GRUPOS],
        "pecas": repositorio.pecas(conexao, id_loja),
        "motivos_entrada": MOTIVOS_ENTRADA,
        "motivos_saida": MOTIVOS_SAIDA,
        "escopo": {
            "papel": usuario.papel.value if usuario.papel else "",
            "id_loja": usuario.id_loja,
            "loja_nome": loja["nome"] if loja else None,
            "pode_escolher_loja": admin,
            "somente_minhas": somente_minhas(usuario),
        },
    }


def montar_saldo(
    conexao: Connection, filtro: FiltroSaldo, *, limit: int, offset: int
) -> dict[str, Any]:
    total, itens = repositorio.itens_do_saldo(conexao, filtro, limit=limit, offset=offset)
    por_loja = repositorio.saldo_por_loja(
        conexao, [i["id_variacao"] for i in itens], filtro.id_loja
    )
    resumo = repositorio.resumo_do_saldo(conexao, filtro.id_loja)
    return {
        "resumo": {
            "unidades": int(resumo["unidades"]),
            "pecas": int(resumo["pecas"]),
            "estoque_baixo": int(resumo["estoque_baixo"]),
            "esgotadas": int(resumo["esgotadas"]),
            "valor_em_estoque": round(float(resumo["valor_em_estoque"]), 2),
        },
        "lojas": repositorio.lojas_visiveis(conexao, filtro.id_loja),
        "total": total,
        "itens": [
            {
                **item,
                "preco": round(float(item["preco"]), 2),
                "por_loja": por_loja.get(item["id_variacao"], []),
            }
            for item in itens
        ],
    }


def validar_periodo(de: date | None, ate: date | None) -> None:
    if de and ate and ate < de:
        raise PeriodoInvalido()


def filtro_de_movimentacoes(
    conexao: Connection,
    usuario: UsuarioAtual,
    *,
    id_loja: UUID | None,
    grupo: str | None,
    sku: str | None,
    de: date | None,
    ate: date | None,
) -> FiltroMovimentacoes:
    validar_periodo(de, ate)
    id_responsavel = None
    if somente_minhas(usuario):
        id_responsavel = id_usuario_ativo(conexao, usuario.id_auth)
        if id_responsavel is None:
            raise SemPermissao()
    return FiltroMovimentacoes(id_loja, grupo, sku, de, ate, id_responsavel)


def montar_movimentacoes(
    conexao: Connection, filtro: FiltroMovimentacoes, *, limit: int, offset: int
) -> dict[str, Any]:
    total, itens = repositorio.movimentacoes(conexao, filtro, limit=limit, offset=offset)
    return {"total": total, "itens": itens}
