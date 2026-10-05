"""Conexao PostgreSQL usada pelo app Flask."""

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from estoque_flask.config import Configuracao


@contextmanager
def abrir_conexao(configuracao: Configuracao) -> Iterator[psycopg.Connection]:
    with psycopg.connect(configuracao.database_url, row_factory=dict_row) as conexao:
        yield conexao
