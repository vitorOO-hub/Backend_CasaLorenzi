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
