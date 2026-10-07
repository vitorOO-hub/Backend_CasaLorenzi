"""Apoio dos testes de banco: troca de papel com claims injetadas e execucao em savepoint."""

import json
from contextlib import contextmanager

import psycopg
from psycopg import sql


@contextmanager
def como(conn, *, role="authenticated", sub=None, papel=None, loja=None):
    """Executa o bloco como `role`, com as claims do JWT que o Supabase injetaria."""
    claims = {"role": role}
    if sub is not None:
        claims["sub"] = str(sub)
    if papel is not None:
        claims["papel"] = papel
    if loja is not None:
        claims["loja_id"] = str(loja)
    conn.execute("SELECT set_config('request.jwt.claims', %s, true)", (json.dumps(claims),))
    conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role)))
    try:
        yield
    finally:
        conn.execute("RESET ROLE")


def tenta(conn, comando, parametros=None):
    """Roda dentro de um savepoint: devolve as linhas, ou a excecao do banco se falhar."""
    try:
        with conn.transaction():
            cursor = conn.execute(comando, parametros)
            return cursor.fetchall() if cursor.description else []
    except psycopg.Error as erro:
        return erro


def e_erro(resultado, tipo=psycopg.errors.InsufficientPrivilege) -> bool:
    return isinstance(resultado, tipo)
