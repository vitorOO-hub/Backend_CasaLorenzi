"""Rotas das automacoes agendadas do n8n (`/api/v1/automacoes`), sem IA.

Nao usam o login de uma pessoa: exigem a chave do cabecalho X-Chave-Automacao (`requer_automacao`).
Sao as mesmas contas do painel e do Lorenzi+, para os tres canais darem sempre o mesmo numero.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.automacoes import emails, service
from app.automacoes.schemas import (
    AvisosEnviados,
    AvisosGravados,
    Canal,
    ClientesAAvisar,
    ResumoSemanal,
)
from app.core.config import Settings, get_settings
from app.core.db import ExecutarDep
from app.core.erros import ErroDeNegocio
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
def resumo_semanal(executar: ExecutarDep, id_loja: UUID | None = None):
    try:
        return executar(lambda conexao: service.resumo_semanal(conexao, id_loja=id_loja))
    except service.LojaDoResumoNaoEncontrada as erro:
        raise HTTPException(status_code=404, detail="Loja ativa não encontrada") from erro


class EmailsIndisponiveis(ErroDeNegocio):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    detalhe = "E-mails desligados: configure N8N_WEBHOOK_EMAILS e CHAVE_AUTOMACAO no servidor."


SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.post("/disparar-emails", summary="Disparo diario: pontos a vencer, categoria e reenvios")
def disparar_emails(
    executar: ExecutarDep, configuracoes: SettingsDep, simular: bool = False
) -> dict:
    """Chamado uma vez por dia pelo agendamento. `simular=true` so lista quem receberia."""
    if not simular and not emails.configurado(configuracoes):
        raise EmailsIndisponiveis()
    return executar(lambda conexao: emails.disparar(conexao, configuracoes, simular=simular))


@router.post("/resumo-da-compra/{id_pedido}", summary="Enviar (uma vez) o resumo de uma compra")
def resumo_da_compra(id_pedido: UUID, executar: ExecutarDep, configuracoes: SettingsDep) -> dict:
    if not emails.configurado(configuracoes):
        raise EmailsIndisponiveis()
    return {
        "situacao": executar(
            lambda conexao: emails.enviar_resumo_da_compra(conexao, configuracoes, id_pedido)
        )
    }
