"""Rotas das automacoes agendadas do n8n (`/api/v1/automacoes`), sem IA.

Nao usam o login de uma pessoa: exigem a chave do cabecalho X-Chave-Automacao (`requer_automacao`).
Sao as mesmas contas do painel e do Lorenzi+, para os tres canais darem sempre o mesmo numero.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.automacoes import emails, service
from app.automacoes.schemas import (
    AvisosEnviados,
    AvisosGravados,
    Canal,
    ClientesAAvisar,
    EmailsEnviados,
    EstoqueDoDia,
    EstoqueParadoPorLoja,
    RelatoriosDeEstoque,
    ResumoSemanal,
    Semanal,
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


@router.get(
    "/relatorios-estoque",
    response_model=RelatoriosDeEstoque,
    summary="E-mails do dia para os operadores de estoque (diario; semanal as segundas)",
)
def relatorios_estoque(
    request: Request,
    executar: ExecutarDep,
    semanal: Semanal = "auto",
    horas_sem_resposta: Annotated[int, Query(ge=1, le=720)] = 24,
    dias_em_transito: Annotated[int, Query(ge=1, le=90)] = 3,
    dias_parado: Annotated[int, Query(ge=7, le=365)] = 60,
    limite: Annotated[int, Query(ge=1, le=100)] = 30,
):
    # O logo e o link do painel nos e-mails saem do endereco do front.
    site = request.app.state.settings.frontend_url.rstrip("/")
    return executar(
        lambda conexao: service.relatorios_estoque(
            conexao,
            semanal=semanal,
            site=site,
            horas=horas_sem_resposta,
            dias=dias_em_transito,
            dias_parado=dias_parado,
            limite=limite,
        )
    )


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


@router.post(
    "/emails-diarios", summary="Disparo diario pelo relogio do n8n: e-mails prontos para enviar"
)
def emails_diarios(executar: ExecutarDep, configuracoes: SettingsDep) -> dict:
    """Devolve os e-mails de pontos e de categoria do dia (o n8n envia). Reenvia, pelo webhook, os
    resumos de compra que falharam. Nao grava aviso: isso e `/emails-diarios/enviados`."""
    return executar(lambda conexao: emails.preparar_diarios(conexao, configuracoes))


@router.post("/emails-diarios/enviados", summary="Registrar os e-mails diarios que o n8n enviou")
def emails_diarios_enviados(dados: EmailsEnviados, executar: ExecutarDep) -> dict:
    return executar(lambda conexao: emails.registrar_enviados(conexao, dados.enviados))


@router.post("/resumo-da-compra/{id_pedido}", summary="Enviar (uma vez) o resumo de uma compra")
def resumo_da_compra(id_pedido: UUID, executar: ExecutarDep, configuracoes: SettingsDep) -> dict:
    if not emails.configurado(configuracoes):
        raise EmailsIndisponiveis()
    return {
        "situacao": executar(
            lambda conexao: emails.enviar_resumo_da_compra(conexao, configuracoes, id_pedido)
        )
    }
