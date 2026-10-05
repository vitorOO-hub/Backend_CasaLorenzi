"""Rotas FastAPI para exercitar as acoes da tabela estoque."""

from typing import Any

from fastapi import FastAPI, status
from fastapi.responses import JSONResponse
from psycopg import errors
from pydantic import BaseModel, Field

from estoque_fastapi.config import Configuracao, carregar_configuracao
from estoque_fastapi.db import abrir_conexao
from estoque_fastapi.repositorio import (
    EstoqueComSaldo,
    EstoqueInsuficiente,
    RegistroNaoEncontrado,
    atualizar_estoque_minimo,
    criar_estoque,
    listar_estoques,
    normalizar_id,
    obter_estoque,
    registrar_entrada,
    registrar_saida,
    remover_estoque_sem_saldo,
)


class EstoqueCriacao(BaseModel):
    id_loja: str | int
    id_variacao: str | int
    quantidade: int = Field(default=0, ge=0)
    estoque_minimo: int = Field(default=0, ge=0)


class QuantidadeEntrada(BaseModel):
    quantidade: int = Field(gt=0)


class EstoqueMinimoEntrada(BaseModel):
    estoque_minimo: int = Field(ge=0)


def criar_app(configuracao: Configuracao | None = None) -> FastAPI:
    app = FastAPI(title="Teste de estoque", version="0.1.0")
    configuracao = configuracao or carregar_configuracao()

    def executar(operacao):
        with abrir_conexao(configuracao) as conexao:
            return operacao(conexao)

    @app.exception_handler(RegistroNaoEncontrado)
    async def erro_nao_encontrado(_request, _erro: RegistroNaoEncontrado):
        return JSONResponse(
            {"detail": "Estoque nao encontrado"},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    @app.exception_handler(EstoqueInsuficiente)
    async def erro_estoque_insuficiente(_request, _erro: EstoqueInsuficiente):
        return JSONResponse(
            {"detail": "Estoque insuficiente para realizar a saida"},
            status_code=status.HTTP_409_CONFLICT,
        )

    @app.exception_handler(EstoqueComSaldo)
    async def erro_estoque_com_saldo(_request, _erro: EstoqueComSaldo):
        return JSONResponse(
            {"detail": "Nao e possivel remover estoque com saldo maior que zero"},
            status_code=status.HTTP_409_CONFLICT,
        )

    @app.exception_handler(errors.UniqueViolation)
    async def erro_unico(_request, _erro: errors.UniqueViolation):
        return JSONResponse(
            {"detail": "Ja existe estoque para esta loja e variacao"},
            status_code=status.HTTP_409_CONFLICT,
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/estoques")
    def listar() -> list[dict[str, Any]]:
        return executar(listar_estoques)

    @app.get("/estoques/{id_estoque}")
    def obter(id_estoque: str) -> dict[str, Any]:
        estoque_id = normalizar_id(id_estoque)
        return executar(lambda conexao: obter_estoque(conexao, estoque_id))

    @app.post("/estoques", status_code=status.HTTP_201_CREATED)
    def criar(dados: EstoqueCriacao) -> dict[str, Any]:
        return executar(
            lambda conexao: criar_estoque(
                conexao,
                id_loja=normalizar_id(dados.id_loja),
                id_variacao=normalizar_id(dados.id_variacao),
                quantidade=dados.quantidade,
                estoque_minimo=dados.estoque_minimo,
            )
        )

    @app.post("/estoques/{id_estoque}/entrada")
    def entrada(id_estoque: str, dados: QuantidadeEntrada) -> dict[str, Any]:
        estoque_id = normalizar_id(id_estoque)
        return executar(
            lambda conexao: registrar_entrada(
                conexao,
                id_estoque=estoque_id,
                quantidade=dados.quantidade,
            )
        )

    @app.post("/estoques/{id_estoque}/saida")
    def saida(id_estoque: str, dados: QuantidadeEntrada) -> dict[str, Any]:
        estoque_id = normalizar_id(id_estoque)
        return executar(
            lambda conexao: registrar_saida(
                conexao,
                id_estoque=estoque_id,
                quantidade=dados.quantidade,
            )
        )

    @app.patch("/estoques/{id_estoque}/minimo")
    def minimo(id_estoque: str, dados: EstoqueMinimoEntrada) -> dict[str, Any]:
        estoque_id = normalizar_id(id_estoque)
        return executar(
            lambda conexao: atualizar_estoque_minimo(
                conexao,
                id_estoque=estoque_id,
                estoque_minimo=dados.estoque_minimo,
            )
        )

    @app.delete("/estoques/{id_estoque}")
    def remover(id_estoque: str) -> dict[str, Any]:
        estoque_id = normalizar_id(id_estoque)
        return executar(lambda conexao: remover_estoque_sem_saldo(conexao, id_estoque=estoque_id))

    return app
