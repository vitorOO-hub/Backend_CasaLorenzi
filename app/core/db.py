"""Conexao com o PostgreSQL do Supabase via SQLAlchemy.

Esta conexao ignora RLS de proposito (CLAUDE.md, secao 2): toda checagem de papel e de
escopo de loja fica no codigo Python. Queries sempre parametrizadas.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy import create_engine
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings, get_settings

Executar = Callable[[Callable[[Connection], Any]], Any]


def _url_sqlalchemy(database_url: str) -> str:
    """Usa SQLAlchemy como padrao sem exigir que o .env mude de formato."""
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    return database_url


@lru_cache
def criar_engine(database_url: str) -> Engine:
    return create_engine(_url_sqlalchemy(database_url), pool_pre_ping=True)


def get_engine(settings: Settings) -> Engine:
    return criar_engine(settings.database_url.get_secret_value())


@contextmanager
def abrir_conexao(settings: Settings) -> Iterator[Connection]:
    with get_engine(settings).connect() as conexao:
        yield conexao


def get_executar(settings: Annotated[Settings, Depends(get_settings)]) -> Executar:
    """Entrega uma funcao que abre a conexao so quando a rota executa uma operacao.

    A conexao e aberta de forma preguicosa, depois da validacao do corpo da requisicao:
    um pedido invalido (422) nunca chega a tocar no banco.
    """

    engine = get_engine(settings)

    def executar(operacao: Callable[[Connection], Any]) -> Any:
        with engine.connect() as conexao:
            return operacao(conexao)

    return executar


ExecutarDep = Annotated[Executar, Depends(get_executar)]


def codigo_integridade(erro: IntegrityError) -> str | None:
    origem = erro.orig
    return getattr(origem, "sqlstate", None) or getattr(origem, "pgcode", None)


def eh_violacao_unicidade(erro: IntegrityError) -> bool:
    return codigo_integridade(erro) == "23505"


def eh_violacao_chave_estrangeira(erro: IntegrityError) -> bool:
    return codigo_integridade(erro) == "23503"


def eh_violacao_check(erro: IntegrityError) -> bool:
    return codigo_integridade(erro) == "23514"
