"""Rotas do inicio do gerente (`/api/v1/painel/gerencia`).

Sempre exigem token valido e papel de gerente ou admin, independente de AUTENTICACAO_OBRIGATORIA:
sao telas novas e nao ha uso anonimo para preservar. O gerente enxerga so a propria loja (a do
token); pedir outra e 403. O admin enxerga a rede ou escolhe uma loja.
"""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.db import ExecutarDep
from app.core.papeis import Papel, UsuarioAtual
from app.core.security import requer_papel
from app.gerencia import service
from app.gerencia.repositorio import Filtro
from app.gerencia.schemas import DashboardGerente, Pendencias, Reposicao

router = APIRouter(prefix="/painel/gerencia", tags=["painel-gerencia"])

UsuarioDep = Annotated[UsuarioAtual, Depends(requer_papel(*service.PAPEIS_DA_GERENCIA))]
IdLoja = Annotated[UUID | None, Query(description="So o admin escolhe a loja")]
Categoria = Annotated[str | None, Query(max_length=80)]
Canal = Annotated[str | None, Query(max_length=10, pattern=r"^(loja|online)$")]


@router.get("/dashboard", response_model=DashboardGerente, summary="Vendas e indicadores")
def dashboard(
    usuario: UsuarioDep,
    executar: ExecutarDep,
    inicio: date,
    fim: date,
    id_loja: IdLoja = None,
    categoria: Categoria = None,
    canal: Canal = None,
):
    service.validar_periodo(inicio, fim)
    filtro = Filtro(service.loja_do_escopo(usuario, id_loja), categoria, canal)
    return executar(
        lambda conexao: service.montar_dashboard(
            conexao, usuario, inicio=inicio, fim=fim, filtro=filtro
        )
    )


@router.get("/reposicao", response_model=Reposicao, summary="Pecas que acabam primeiro")
def reposicao(
    usuario: UsuarioDep,
    executar: ExecutarDep,
    id_loja: IdLoja = None,
    categoria: Categoria = None,
    limit: int = Query(default=6, ge=1, le=50),
):
    filtro = Filtro(service.loja_do_escopo(usuario, id_loja), categoria)
    return executar(lambda conexao: service.montar_reposicao(conexao, filtro, limite=limit))


@router.get("/pendencias", response_model=Pendencias, summary="O que espera uma acao do gerente")
def pendencias(usuario: UsuarioDep, executar: ExecutarDep, id_loja: IdLoja = None):
    filtro = Filtro(service.loja_do_escopo(usuario, id_loja))
    # Equipe de loja tambem atende os chamados sem loja; o admin olhando a rede ja os inclui.
    sem_loja = usuario.papel is not Papel.ADMIN
    return executar(
        lambda conexao: service.montar_pendencias(
            conexao, filtro, incluir_chamados_sem_loja=sem_loja
        )
    )
