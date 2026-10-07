"""Rotas do saldo e do historico de movimentacoes (`/api/v1/painel/estoque`).

Sempre exigem token valido e papel de operador de estoque, gerente ou admin, independente de
AUTENTICACAO_OBRIGATORIA: sao telas novas e nao ha uso anonimo para preservar. Operador e gerente
enxergam so a propria loja (a do token; pedir outra e 403); o admin ve a rede ou escolhe uma loja.
O operador ainda so ve as movimentacoes que ele mesmo registrou.
"""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.db import ExecutarDep
from app.core.papeis import UsuarioAtual
from app.core.security import requer_papel
from app.painel_estoque import service
from app.painel_estoque.repositorio import FiltroSaldo
from app.painel_estoque.schemas import Movimentacoes, Opcoes, Saldo

router = APIRouter(prefix="/painel/estoque", tags=["painel-estoque"])

UsuarioDep = Annotated[UsuarioAtual, Depends(requer_papel(*service.PAPEIS_DO_ESTOQUE))]
IdLoja = Annotated[UUID | None, Query(description="So o admin escolhe a loja")]
Texto = Annotated[str | None, Query(max_length=80)]
Situacao = Annotated[str | None, Query(pattern=r"^(ok|baixo|esgotado)$")]
Tipo = Annotated[str | None, Query(pattern=r"^(entrada|saida|ajuste|transferencia)$")]
Sku = Annotated[str | None, Query(max_length=60)]


@router.get("/opcoes", response_model=Opcoes, summary="Filtros das telas de estoque")
def opcoes(usuario: UsuarioDep, executar: ExecutarDep, id_loja: IdLoja = None):
    loja = service.loja_do_escopo(usuario, id_loja)
    return executar(lambda conexao: service.montar_opcoes(conexao, usuario, loja))


@router.get("/saldo", response_model=Saldo, summary="Saldo de estoque por peca")
def saldo(
    usuario: UsuarioDep,
    executar: ExecutarDep,
    id_loja: IdLoja = None,
    busca: Texto = None,
    categoria: Texto = None,
    situacao: Situacao = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    filtro = FiltroSaldo(service.loja_do_escopo(usuario, id_loja), busca, categoria, situacao)
    return executar(
        lambda conexao: service.montar_saldo(conexao, filtro, limit=limit, offset=offset)
    )


@router.get("/movimentacoes", response_model=Movimentacoes, summary="Historico de movimentacoes")
def movimentacoes(
    usuario: UsuarioDep,
    executar: ExecutarDep,
    id_loja: IdLoja = None,
    tipo: Tipo = None,
    sku: Sku = None,
    de: date | None = None,
    ate: date | None = None,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    loja = service.loja_do_escopo(usuario, id_loja)

    def operacao(conexao):
        filtro = service.filtro_de_movimentacoes(
            conexao, usuario, id_loja=loja, grupo=tipo, sku=sku, de=de, ate=ate
        )
        return service.montar_movimentacoes(conexao, filtro, limit=limit, offset=offset)

    return executar(operacao)
