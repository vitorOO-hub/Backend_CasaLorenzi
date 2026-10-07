"""Rotas do dashboard de atendimento (home do atendente).

Sempre exigem token valido e um destes papeis, independente de AUTENTICACAO_OBRIGATORIA: o
dashboard e novo e nao tem tela anonima para preservar.
"""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.db import ExecutarDep
from app.core.papeis import Papel, UsuarioAtual
from app.core.security import requer_papel
from app.dashboard import service
from app.dashboard.repositorio import Filtro
from app.dashboard.schemas import DashboardAtendimento, FilaAtendimento

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

UsuarioDep = Annotated[UsuarioAtual, Depends(requer_papel(*service.PAPEIS_DO_DASHBOARD))]
CodigoOpcional = Annotated[str | None, Query(max_length=40, pattern=r"^[a-z0-9_]+$")]


def _filtro(
    usuario: UsuarioAtual, id_loja: UUID | None, canal: str | None, categoria: str | None
) -> Filtro:
    """Admin: a rede ou uma loja. Equipe de loja: a propria loja mais os chamados sem loja."""
    return Filtro(
        service.resolver_loja(usuario, id_loja),
        canal,
        categoria,
        incluir_sem_loja=usuario.papel is not Papel.ADMIN,
    )


@router.get("/atendimento", response_model=DashboardAtendimento, summary="Indicadores do periodo")
def dashboard_atendimento(
    usuario: UsuarioDep,
    executar: ExecutarDep,
    inicio: date,
    fim: date,
    id_loja: UUID | None = None,
    canal: CodigoOpcional = None,
    categoria: CodigoOpcional = None,
):
    service.validar_periodo(inicio, fim)
    filtro = _filtro(usuario, id_loja, canal, categoria)
    return executar(
        lambda conexao: service.montar_dashboard(
            conexao, usuario, inicio=inicio, fim=fim, filtro=filtro
        )
    )


@router.get("/atendimento/fila", response_model=FilaAtendimento, summary="Fila de chamados")
def fila_de_atendimento(
    usuario: UsuarioDep,
    executar: ExecutarDep,
    id_loja: UUID | None = None,
    canal: CodigoOpcional = None,
    categoria: CodigoOpcional = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    filtro = _filtro(usuario, id_loja, canal, categoria)
    return executar(
        lambda conexao: service.montar_fila(conexao, filtro, limit=limit, offset=offset)
    )
