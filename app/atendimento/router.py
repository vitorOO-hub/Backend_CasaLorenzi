"""Rotas de atendimento, mensagens e avaliacoes."""

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError

from app.atendimento import service
from app.atendimento.erros import (
    AtendimentoInvalido,
    ReferenciaAtendimentoInvalida,
    RegistroAtendimentoDuplicado,
)
from app.atendimento.schemas import (
    AtendimentoAtualizacao,
    AtendimentoCriacao,
    AtendimentoItemCriacao,
    AvaliacaoAtendimentoCriacao,
    MensagemCriacao,
    RegistroAtendimentoLeitura,
    ResponsavelAtendimentoAtualizacao,
    StatusAtendimentoAtualizacao,
)
from app.core.db import (
    ExecutarDep,
    eh_violacao_chave_estrangeira,
    eh_violacao_check,
    eh_violacao_unicidade,
)

router = APIRouter(prefix="/atendimentos", tags=["atendimentos"])

Pagina = Query(default=20, ge=1, le=100)
Deslocamento = Query(default=0, ge=0)


def _dados(modelo) -> dict[str, object]:
    return modelo.model_dump(exclude_none=True)


def _executar_com_tratamento(executar: ExecutarDep, operacao) -> Any:
    try:
        return executar(operacao)
    except ValueError as erro:
        raise HTTPException(status_code=422, detail=str(erro)) from erro
    except IntegrityError as erro:
        if eh_violacao_unicidade(erro):
            raise RegistroAtendimentoDuplicado from erro
        if eh_violacao_chave_estrangeira(erro):
            raise ReferenciaAtendimentoInvalida from erro
        if eh_violacao_check(erro):
            raise AtendimentoInvalido from erro
        raise


@router.get("/opcoes/{nome_opcao}", response_model=list[RegistroAtendimentoLeitura])
def listar_opcoes(
    nome_opcao: str,
    executar: ExecutarDep,
    limit: int = Pagina,
    offset: int = Deslocamento,
):
    if nome_opcao not in service.TABELAS_OPCOES:
        raise HTTPException(status_code=404, detail="Opcao de atendimento nao encontrada")
    return executar(
        lambda conexao: service.listar_opcoes(conexao, nome_opcao, limit=limit, offset=offset)
    )


@router.get("", response_model=list[RegistroAtendimentoLeitura])
def listar_atendimentos(executar: ExecutarDep, limit: int = Pagina, offset: int = Deslocamento):
    return executar(lambda conexao: service.listar_atendimentos(conexao, limit=limit, offset=offset))


@router.post("", status_code=status.HTTP_201_CREATED, response_model=RegistroAtendimentoLeitura)
def criar_atendimento(dados: AtendimentoCriacao, executar: ExecutarDep):
    return _executar_com_tratamento(
        executar,
        lambda conexao: service.criar_atendimento(conexao, _dados(dados)),
    )


@router.get("/{id_atendimento}", response_model=RegistroAtendimentoLeitura)
def obter_atendimento(id_atendimento: str, executar: ExecutarDep):
    return executar(lambda conexao: service.obter_atendimento(conexao, id_atendimento))


@router.patch("/{id_atendimento}", response_model=RegistroAtendimentoLeitura)
def atualizar_atendimento(
    id_atendimento: str,
    dados: AtendimentoAtualizacao,
    executar: ExecutarDep,
):
    return _executar_com_tratamento(
        executar,
        lambda conexao: service.atualizar_atendimento(conexao, id_atendimento, _dados(dados)),
    )


@router.patch("/{id_atendimento}/status", response_model=RegistroAtendimentoLeitura)
def atualizar_status(
    id_atendimento: str,
    dados: StatusAtendimentoAtualizacao,
    executar: ExecutarDep,
):
    return _executar_com_tratamento(
        executar,
        lambda conexao: service.atualizar_status(conexao, id_atendimento, _dados(dados)),
    )


@router.patch("/{id_atendimento}/responsavel", response_model=RegistroAtendimentoLeitura)
def atualizar_responsavel(
    id_atendimento: str,
    dados: ResponsavelAtendimentoAtualizacao,
    executar: ExecutarDep,
):
    return _executar_com_tratamento(
        executar,
        lambda conexao: service.atualizar_responsavel(
            conexao,
            id_atendimento,
            dados.id_usuario_responsavel,
        ),
    )


@router.get("/{id_atendimento}/mensagens", response_model=list[RegistroAtendimentoLeitura])
def listar_mensagens(id_atendimento: str, executar: ExecutarDep):
    return executar(lambda conexao: service.listar_mensagens(conexao, id_atendimento))


@router.post(
    "/{id_atendimento}/mensagens",
    status_code=status.HTTP_201_CREATED,
    response_model=RegistroAtendimentoLeitura,
)
def criar_mensagem(id_atendimento: str, dados: MensagemCriacao, executar: ExecutarDep):
    return _executar_com_tratamento(
        executar,
        lambda conexao: service.criar_mensagem(conexao, id_atendimento, _dados(dados)),
    )


@router.get("/{id_atendimento}/itens", response_model=list[RegistroAtendimentoLeitura])
def listar_itens(id_atendimento: str, executar: ExecutarDep):
    return executar(lambda conexao: service.listar_itens(conexao, id_atendimento))


@router.post(
    "/{id_atendimento}/itens",
    status_code=status.HTTP_201_CREATED,
    response_model=RegistroAtendimentoLeitura,
)
def vincular_item(id_atendimento: str, dados: AtendimentoItemCriacao, executar: ExecutarDep):
    return _executar_com_tratamento(
        executar,
        lambda conexao: service.vincular_item(conexao, id_atendimento, _dados(dados)),
    )


@router.post(
    "/{id_atendimento}/avaliacao",
    status_code=status.HTTP_201_CREATED,
    response_model=RegistroAtendimentoLeitura,
)
def criar_avaliacao(
    id_atendimento: str,
    dados: AvaliacaoAtendimentoCriacao,
    executar: ExecutarDep,
):
    return _executar_com_tratamento(
        executar,
        lambda conexao: service.criar_avaliacao(conexao, id_atendimento, _dados(dados)),
    )
