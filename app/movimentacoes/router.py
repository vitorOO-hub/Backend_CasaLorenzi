"""Rotas da tabela movimentacao_estoque."""

from fastapi import APIRouter, Query

from app.core.db import ExecutarDep
from app.movimentacoes import service
from app.movimentacoes.schemas import MovimentacaoLeitura

router = APIRouter(
    prefix="/movimentacoes-estoque",
    tags=["movimentacoes-estoque"],
)

Pagina = Query(default=20, ge=1, le=100)
Deslocamento = Query(default=0, ge=0)


@router.get("", response_model=list[MovimentacaoLeitura])
def listar(executar: ExecutarDep, limit: int = Pagina, offset: int = Deslocamento):
    return executar(lambda conexao: service.listar_movimentacoes(conexao, limit=limit, offset=offset))


@router.get("/{id_movimentacao}", response_model=MovimentacaoLeitura)
def obter(id_movimentacao: str, executar: ExecutarDep):
    return executar(lambda conexao: service.obter_movimentacao(conexao, id_movimentacao))

