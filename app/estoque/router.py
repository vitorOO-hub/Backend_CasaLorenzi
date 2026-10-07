"""Rotas do modulo de estoque."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.core.db import ExecutarDep
from app.core.papeis import Papel, UsuarioAtual
from app.core.security import requer_papel
from app.estoque.repositorio import (
    ajustar_inventario_com_historico,
    listar_estoques,
    normalizar_id,
    obter_estoque,
    registrar_entrada_com_historico,
    registrar_saida_com_historico,
)
from app.estoque.schemas import AjusteInventarioEntrada, QuantidadeEntrada

OperadorEstoque = Annotated[UsuarioAtual, Depends(requer_papel(Papel.OPERADOR_ESTOQUE))]

router = APIRouter(prefix="/estoques", tags=["estoque"])


@router.get("")
def listar(executar: ExecutarDep) -> list[dict[str, Any]]:
    return executar(listar_estoques)


@router.get("/{id_estoque}")
def obter(id_estoque: str, executar: ExecutarDep) -> dict[str, Any]:
    estoque_id = normalizar_id(id_estoque)
    return executar(lambda conexao: obter_estoque(conexao, estoque_id))


@router.post("/{id_estoque}/entrada")
def entrada(
    id_estoque: str,
    dados: QuantidadeEntrada,
    usuario: OperadorEstoque,
    executar: ExecutarDep,
) -> dict[str, Any]:
    estoque_id = normalizar_id(id_estoque)
    return executar(
        lambda conexao: registrar_entrada_com_historico(
            conexao,
            id_estoque=estoque_id,
            auth_user_id_responsavel=usuario.id_auth,
            quantidade=dados.quantidade,
            motivo=dados.motivo,
        )
    )


@router.post("/{id_estoque}/saida")
def saida(
    id_estoque: str,
    dados: QuantidadeEntrada,
    usuario: OperadorEstoque,
    executar: ExecutarDep,
) -> dict[str, Any]:
    estoque_id = normalizar_id(id_estoque)
    return executar(
        lambda conexao: registrar_saida_com_historico(
            conexao,
            id_estoque=estoque_id,
            auth_user_id_responsavel=usuario.id_auth,
            quantidade=dados.quantidade,
            motivo=dados.motivo,
        )
    )


@router.post("/{id_estoque}/ajuste")
def ajuste(
    id_estoque: str,
    dados: AjusteInventarioEntrada,
    usuario: OperadorEstoque,
    executar: ExecutarDep,
) -> dict[str, Any]:
    estoque_id = normalizar_id(id_estoque)
    return executar(
        lambda conexao: ajustar_inventario_com_historico(
            conexao,
            id_estoque=estoque_id,
            auth_user_id_responsavel=usuario.id_auth,
            quantidade_real=dados.quantidade,
            motivo=dados.motivo,
        )
    )
