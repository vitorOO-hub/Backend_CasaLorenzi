"""Rotas da tabela movimentacao_estoque."""

from fastapi import APIRouter, Query, status
from sqlalchemy.exc import IntegrityError

from app.core.db import (
    ExecutarDep,
    eh_violacao_chave_estrangeira,
    eh_violacao_check,
)
from app.movimentacoes import service
from app.movimentacoes.erros import MovimentacaoInvalida
from app.movimentacoes.schemas import MovimentacaoCriacao, MovimentacaoLeitura

router = APIRouter(prefix="/movimentacoes-estoque", tags=["movimentacoes-estoque"])

Pagina = Query(default=20, ge=1, le=100)
Deslocamento = Query(default=0, ge=0)


@router.get("", response_model=list[MovimentacaoLeitura])
def listar(executar: ExecutarDep, limit: int = Pagina, offset: int = Deslocamento):
    return executar(lambda conexao: service.listar_movimentacoes(conexao, limit=limit, offset=offset))


@router.get("/{id_movimentacao}", response_model=MovimentacaoLeitura)
def obter(id_movimentacao: str, executar: ExecutarDep):
    return executar(lambda conexao: service.obter_movimentacao(conexao, id_movimentacao))


@router.post("", status_code=status.HTTP_201_CREATED, response_model=MovimentacaoLeitura)
def criar(dados: MovimentacaoCriacao, executar: ExecutarDep):
    try:
        return executar(lambda conexao: service.criar_movimentacao(conexao, dados.model_dump()))
    except IntegrityError as erro:
        if eh_violacao_chave_estrangeira(erro) or eh_violacao_check(erro):
            raise MovimentacaoInvalida from erro
        raise
