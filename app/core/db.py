"""Conexao com o PostgreSQL do Supabase (psycopg, sincrona).

Esta conexao ignora RLS de proposito (CLAUDE.md, secao 2): toda checagem de papel e de
escopo de loja fica no codigo Python. Queries sempre parametrizadas.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Annotated, Any

import psycopg
from fastapi import Depends
from psycopg.rows import dict_row

from app.core.config import Settings, get_settings

Executar = Callable[[Callable[[psycopg.Connection], Any]], Any]


@contextmanager
def abrir_conexao(settings: Settings) -> Iterator[psycopg.Connection]:
    with psycopg.connect(settings.database_url.get_secret_value(), row_factory=dict_row) as conexao:
        yield conexao


def get_executar(settings: Annotated[Settings, Depends(get_settings)]) -> Executar:
    """Entrega uma funcao que abre a conexao so quando a rota executa uma operacao.

    A conexao e aberta de forma preguicosa, depois da validacao do corpo da requisicao:
    um pedido invalido (422) nunca chega a tocar no banco.
    """

    def executar(operacao: Callable[[psycopg.Connection], Any]) -> Any:
        with abrir_conexao(settings) as conexao:
            return operacao(conexao)

    return executar


ExecutarDep = Annotated[Executar, Depends(get_executar)]
