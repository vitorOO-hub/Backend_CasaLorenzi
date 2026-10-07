"""Rotas do saldo, do historico e da escrita do estoque (`/api/v1/painel/estoque`).

Sempre exigem token valido e papel de operador de estoque, gerente ou admin, independente de
AUTENTICACAO_OBRIGATORIA: sao telas novas e nao ha uso anonimo para preservar. Operador e gerente
enxergam e mexem so na propria loja (a do token; pedir outra e 403); o admin ve a rede e informa a
loja ao escrever. O operador ainda so ve as movimentacoes e os ajustes que ele mesmo registrou.
Aprovar ou recusar ajuste e so do gerente e do admin.
"""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.core.db import ExecutarDep
from app.core.papeis import UsuarioAtual
from app.core.security import requer_papel
from app.painel_estoque import service, service_escrita
from app.painel_estoque.entradas import NovaMovimentacao, NovoAjuste, Recusa
from app.painel_estoque.repositorio import FiltroSaldo
from app.painel_estoque.schemas import (
    Ajustes,
    ItemAjuste,
    ItemMovimentacao,
    Movimentacoes,
    Opcoes,
    Saldo,
)

router = APIRouter(prefix="/painel/estoque", tags=["painel-estoque"])

UsuarioDep = Annotated[UsuarioAtual, Depends(requer_papel(*service.PAPEIS_DO_ESTOQUE))]
GestaoDep = Annotated[UsuarioAtual, Depends(requer_papel(*service_escrita.PAPEIS_DA_GESTAO))]
IdLoja = Annotated[UUID | None, Query(description="So o admin escolhe a loja")]
Texto = Annotated[str | None, Query(max_length=80)]
Situacao = Annotated[str | None, Query(pattern=r"^(ok|baixo|esgotado)$")]
Tipo = Annotated[str | None, Query(pattern=r"^(entrada|saida|ajuste|transferencia)$")]
Sku = Annotated[str | None, Query(max_length=60)]
StatusDoAjuste = Annotated[str | None, Query(pattern=r"^(pendente|aprovado|rejeitado|decididos)$")]


@router.get("/opcoes", response_model=Opcoes, summary="Filtros das telas de estoque")
def opcoes(usuario: UsuarioDep, executar: ExecutarDep, id_loja: IdLoja = None):
    loja = service.loja_do_escopo(usuario, id_loja)
    return executar(lambda conexao: service.montar_opcoes(conexao, usuario, loja))


@router.get("/saldo", response_model=Saldo, summary="Saldo de estoque por peca")
def saldo(
    usuario: UsuarioDep,
    executar: ExecutarDep,
    id_loja: IdLoja = None,
    busca: Texto = None,
    categoria: Texto = None,
    situacao: Situacao = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    filtro = FiltroSaldo(service.loja_do_escopo(usuario, id_loja), busca, categoria, situacao)
    return executar(
        lambda conexao: service.montar_saldo(conexao, filtro, limit=limit, offset=offset)
    )


@router.get("/movimentacoes", response_model=Movimentacoes, summary="Historico de movimentacoes")
def movimentacoes(
    usuario: UsuarioDep,
    executar: ExecutarDep,
    id_loja: IdLoja = None,
    tipo: Tipo = None,
    sku: Sku = None,
    de: date | None = None,
    ate: date | None = None,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    loja = service.loja_do_escopo(usuario, id_loja)

    def operacao(conexao):
        filtro = service.filtro_de_movimentacoes(
            conexao, usuario, id_loja=loja, grupo=tipo, sku=sku, de=de, ate=ate
        )
        return service.montar_movimentacoes(conexao, filtro, limit=limit, offset=offset)

    return executar(operacao)


@router.post(
    "/movimentacoes",
    response_model=ItemMovimentacao,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar entrada ou saida",
)
def registrar_movimentacao(dados: NovaMovimentacao, usuario: UsuarioDep, executar: ExecutarDep):
    return executar(
        lambda conexao: service_escrita.registrar_movimentacao(
            conexao,
            usuario,
            id_loja=dados.id_loja,
            sku=dados.sku,
            tipo=dados.tipo,
            quantidade=dados.quantidade,
            motivo=dados.motivo,
        )
    )


@router.get("/ajustes", response_model=Ajustes, summary="Ajustes de inventario")
def ajustes(
    usuario: UsuarioDep,
    executar: ExecutarDep,
    id_loja: IdLoja = None,
    situacao: StatusDoAjuste = None,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return executar(
        lambda conexao: service_escrita.listar_ajustes(
            conexao, usuario, id_loja=id_loja, status=situacao, limit=limit, offset=offset
        )
    )


@router.post(
    "/ajustes",
    response_model=ItemAjuste,
    status_code=status.HTTP_201_CREATED,
    summary="Solicitar ajuste de inventario",
)
def solicitar_ajuste(dados: NovoAjuste, usuario: UsuarioDep, executar: ExecutarDep):
    return executar(
        lambda conexao: service_escrita.solicitar_ajuste(
            conexao,
            usuario,
            id_loja=dados.id_loja,
            sku=dados.sku,
            quantidade_contada=dados.quantidade_contada,
            motivo=dados.motivo,
        )
    )


@router.post("/ajustes/{id_ajuste}/aprovar", response_model=ItemAjuste, summary="Aprovar ajuste")
def aprovar_ajuste(id_ajuste: UUID, usuario: GestaoDep, executar: ExecutarDep):
    return executar(lambda conexao: service_escrita.aprovar_ajuste(conexao, usuario, id_ajuste))


@router.post("/ajustes/{id_ajuste}/recusar", response_model=ItemAjuste, summary="Recusar ajuste")
def recusar_ajuste(id_ajuste: UUID, dados: Recusa, usuario: GestaoDep, executar: ExecutarDep):
    return executar(
        lambda conexao: service_escrita.recusar_ajuste(conexao, usuario, id_ajuste, dados.motivo)
    )
