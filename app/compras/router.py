"""Rotas de compras: pedidos, itens e pagamentos."""

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from psycopg import errors

from app.compras import service
from app.compras.erros import CompraDuplicada, ReferenciaCompraInvalida
from app.compras.schemas import (
    ItemPedidoAtualizacao,
    ItemPedidoCriacao,
    PagamentoCriacao,
    PedidoAtualizacao,
    PedidoCriacao,
    RegistroCompraLeitura,
    StatusPagamentoAtualizacao,
    StatusPedidoAtualizacao,
)
from app.core.db import ExecutarDep

router = APIRouter(prefix="/compras", tags=["compras"])

Pagina = Query(default=20, ge=1, le=100)
Deslocamento = Query(default=0, ge=0)


def _dados(modelo) -> dict[str, object]:
    return modelo.model_dump(exclude_none=True)


def _executar_com_tratamento(executar: ExecutarDep, operacao) -> Any:
    try:
        return executar(operacao)
    except ValueError as erro:
        raise HTTPException(status_code=422, detail=str(erro)) from erro
    except errors.UniqueViolation as erro:
        raise CompraDuplicada from erro
    except errors.ForeignKeyViolation as erro:
        raise ReferenciaCompraInvalida from erro


@router.get("/pedidos", response_model=list[RegistroCompraLeitura])
def listar_pedidos(executar: ExecutarDep, limit: int = Pagina, offset: int = Deslocamento):
    return executar(lambda conexao: service.listar_pedidos(conexao, limit=limit, offset=offset))


@router.get("/pedidos/{id_pedido}", response_model=RegistroCompraLeitura)
def obter_pedido(id_pedido: str, executar: ExecutarDep):
    return executar(lambda conexao: service.obter_pedido(conexao, id_pedido))


@router.post("/pedidos", status_code=status.HTTP_201_CREATED, response_model=RegistroCompraLeitura)
def criar_pedido(dados: PedidoCriacao, executar: ExecutarDep):
    return _executar_com_tratamento(
        executar,
        lambda conexao: service.criar_pedido(conexao, _dados(dados)),
    )


@router.patch("/pedidos/{id_pedido}", response_model=RegistroCompraLeitura)
def atualizar_pedido(id_pedido: str, dados: PedidoAtualizacao, executar: ExecutarDep):
    return _executar_com_tratamento(
        executar,
        lambda conexao: service.atualizar_pedido(conexao, id_pedido, _dados(dados)),
    )


@router.patch("/pedidos/{id_pedido}/status", response_model=RegistroCompraLeitura)
def atualizar_status_pedido(id_pedido: str, dados: StatusPedidoAtualizacao, executar: ExecutarDep):
    return _executar_com_tratamento(
        executar,
        lambda conexao: service.atualizar_status_pedido(
            conexao,
            id_pedido,
            dados.id_status_pedido,
        ),
    )


@router.post("/pedidos/{id_pedido}/cancelar", response_model=RegistroCompraLeitura)
def cancelar_pedido(id_pedido: str, executar: ExecutarDep):
    return executar(lambda conexao: service.cancelar_pedido(conexao, id_pedido))


@router.get("/pedidos/{id_pedido}/itens", response_model=list[RegistroCompraLeitura])
def listar_itens_pedido(id_pedido: str, executar: ExecutarDep):
    return executar(lambda conexao: service.listar_itens_pedido(conexao, id_pedido))


@router.post(
    "/pedidos/{id_pedido}/itens",
    status_code=status.HTTP_201_CREATED,
    response_model=RegistroCompraLeitura,
)
def criar_item_pedido(id_pedido: str, dados: ItemPedidoCriacao, executar: ExecutarDep):
    return _executar_com_tratamento(
        executar,
        lambda conexao: service.criar_item_pedido(conexao, id_pedido, _dados(dados)),
    )


@router.get("/itens-pedido/{id_item_pedido}", response_model=RegistroCompraLeitura)
def obter_item_pedido(id_item_pedido: str, executar: ExecutarDep):
    return executar(lambda conexao: service.obter_item_pedido(conexao, id_item_pedido))


@router.patch("/itens-pedido/{id_item_pedido}", response_model=RegistroCompraLeitura)
def atualizar_item_pedido(id_item_pedido: str, dados: ItemPedidoAtualizacao, executar: ExecutarDep):
    return _executar_com_tratamento(
        executar,
        lambda conexao: service.atualizar_item_pedido(conexao, id_item_pedido, _dados(dados)),
    )


@router.delete("/itens-pedido/{id_item_pedido}", response_model=RegistroCompraLeitura)
def remover_item_pedido(id_item_pedido: str, executar: ExecutarDep):
    return executar(lambda conexao: service.remover_item_pedido(conexao, id_item_pedido))


@router.get("/pedidos/{id_pedido}/pagamentos", response_model=list[RegistroCompraLeitura])
def listar_pagamentos_pedido(id_pedido: str, executar: ExecutarDep):
    return executar(lambda conexao: service.listar_pagamentos_pedido(conexao, id_pedido))


@router.post(
    "/pedidos/{id_pedido}/pagamentos",
    status_code=status.HTTP_201_CREATED,
    response_model=RegistroCompraLeitura,
)
def criar_pagamento(id_pedido: str, dados: PagamentoCriacao, executar: ExecutarDep):
    return _executar_com_tratamento(
        executar,
        lambda conexao: service.criar_pagamento(conexao, id_pedido, _dados(dados)),
    )


@router.get("/pagamentos/{id_pagamento}", response_model=RegistroCompraLeitura)
def obter_pagamento(id_pagamento: str, executar: ExecutarDep):
    return executar(lambda conexao: service.obter_pagamento(conexao, id_pagamento))


@router.patch("/pagamentos/{id_pagamento}/status", response_model=RegistroCompraLeitura)
def atualizar_status_pagamento(
    id_pagamento: str,
    dados: StatusPagamentoAtualizacao,
    executar: ExecutarDep,
):
    return _executar_com_tratamento(
        executar,
        lambda conexao: service.atualizar_status_pagamento(
            conexao,
            id_pagamento,
            _dados(dados),
        ),
    )
