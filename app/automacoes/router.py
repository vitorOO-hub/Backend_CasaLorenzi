"""Rotas das automacoes agendadas do n8n (`/api/v1/automacoes`), sem IA.

Nao usam o login de uma pessoa: exigem a chave do cabecalho X-Chave-Automacao (`requer_automacao`).
Sao as mesmas contas do painel e do Lorenzi+, para os tres canais darem sempre o mesmo numero.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.automacoes import service
from app.automacoes.schemas import (
    AvisosEnviados,
    AvisosGravados,
    Canal,
    ClientesAAvisar,
    EstoqueDoDia,
    EstoqueParadoPorLoja,
    ResumoSemanal,
)
from app.core.db import ExecutarDep
from app.core.security import requer_automacao

router = APIRouter(
    prefix="/automacoes", tags=["automacoes"], dependencies=[Depends(requer_automacao)]
)


@router.get(
    "/pontos-a-vencer",
    response_model=ClientesAAvisar,
    summary="Clientes a avisar sobre pontos que vao vencer",
)
def pontos_a_vencer(
    executar: ExecutarDep,
    canal: Canal = "email",
    dias: Annotated[int, Query(ge=1, le=90)] = 30,
):
    return executar(lambda conexao: service.clientes_a_avisar(conexao, dias=dias, canal=canal))


@router.post("/avisos-pontos", response_model=AvisosGravados, summary="Registrar avisos enviados")
def avisos_pontos(dados: AvisosEnviados, executar: ExecutarDep):
    return executar(lambda conexao: service.registrar_avisos(conexao, dados.canal, dados.avisos))


@router.get("/resumo-semanal", response_model=ResumoSemanal, summary="Numeros da semana")
def resumo_semanal(executar: ExecutarDep):
    return executar(service.resumo_semanal)


@router.get(
    "/estoque-do-dia",
    response_model=EstoqueDoDia,
    summary="Por loja: pecas abaixo do minimo e pendencias paradas",
)
def estoque_do_dia(
    executar: ExecutarDep,
    horas_sem_resposta: Annotated[int, Query(ge=1, le=720)] = 24,
    dias_em_transito: Annotated[int, Query(ge=1, le=90)] = 3,
):
    return executar(
        lambda conexao: service.estoque_do_dia(
            conexao, horas=horas_sem_resposta, dias=dias_em_transito
        )
    )


@router.get(
    "/estoque-parado",
    response_model=EstoqueParadoPorLoja,
    summary="Por loja: pecas sem venda ha N dias",
)
def estoque_parado(
    executar: ExecutarDep,
    dias: Annotated[int, Query(ge=7, le=365)] = 60,
    limite: Annotated[int, Query(ge=1, le=100)] = 20,
):
    return executar(
        lambda conexao: service.estoque_parado_por_loja(conexao, dias=dias, limite=limite)
    )
