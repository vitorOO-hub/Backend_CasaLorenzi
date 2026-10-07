"""Rotas do modulo de estoque."""

from typing import Any

from fastapi import APIRouter, status
from sqlalchemy.exc import IntegrityError

from app.core.db import ExecutarDep, eh_violacao_unicidade
from app.estoque.erros import EstoqueDuplicado
from app.estoque.repositorio import (
    atualizar_estoque_minimo,
    criar_estoque,
    listar_estoques,
    normalizar_id,
    obter_estoque,
    registrar_entrada,
    registrar_saida,
    remover_estoque_sem_saldo,
)
from app.estoque.schemas import EstoqueCriacao, EstoqueMinimoEntrada, QuantidadeEntrada

router = APIRouter(prefix="/estoques", tags=["estoque"])


@router.get("")
def listar(executar: ExecutarDep) -> list[dict[str, Any]]:
    return executar(listar_estoques)


@router.get("/{id_estoque}")
def obter(id_estoque: str, executar: ExecutarDep) -> dict[str, Any]:
    estoque_id = normalizar_id(id_estoque)
    return executar(lambda conexao: obter_estoque(conexao, estoque_id))


@router.post("", status_code=status.HTTP_201_CREATED)
def criar(dados: EstoqueCriacao, executar: ExecutarDep) -> dict[str, Any]:
    try:
        return executar(
            lambda conexao: criar_estoque(
                conexao,
                id_loja=normalizar_id(dados.id_loja),
                id_variacao=normalizar_id(dados.id_variacao),
                quantidade=dados.quantidade,
                estoque_minimo=dados.estoque_minimo,
            )
        )
    except IntegrityError as erro:
        if eh_violacao_unicidade(erro):
            raise EstoqueDuplicado from erro
        raise


@router.post("/{id_estoque}/entrada")
def entrada(id_estoque: str, dados: QuantidadeEntrada, executar: ExecutarDep) -> dict[str, Any]:
    estoque_id = normalizar_id(id_estoque)
    return executar(
        lambda conexao: registrar_entrada(
            conexao,
            id_estoque=estoque_id,
            quantidade=dados.quantidade,
        )
    )


@router.post("/{id_estoque}/saida")
def saida(id_estoque: str, dados: QuantidadeEntrada, executar: ExecutarDep) -> dict[str, Any]:
    estoque_id = normalizar_id(id_estoque)
    return executar(
        lambda conexao: registrar_saida(
            conexao,
            id_estoque=estoque_id,
            quantidade=dados.quantidade,
        )
    )


@router.patch("/{id_estoque}/minimo")
def minimo(id_estoque: str, dados: EstoqueMinimoEntrada, executar: ExecutarDep) -> dict[str, Any]:
    estoque_id = normalizar_id(id_estoque)
    return executar(
        lambda conexao: atualizar_estoque_minimo(
            conexao,
            id_estoque=estoque_id,
            estoque_minimo=dados.estoque_minimo,
        )
    )


@router.delete("/{id_estoque}")
def remover(id_estoque: str, executar: ExecutarDep) -> dict[str, Any]:
    estoque_id = normalizar_id(id_estoque)
    return executar(lambda conexao: remover_estoque_sem_saldo(conexao, id_estoque=estoque_id))
