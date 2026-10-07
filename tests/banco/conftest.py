"""Fixtures dos testes de banco: Postgres local com o schema do Supabase e o Alembic aplicados.

Os testes so rodam com TEST_DATABASE_URL apontando para um banco LOCAL cujo nome termina em
"_teste". Qualquer outro destino (por exemplo o Supabase remoto) e recusado com erro.
"""

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
import pytest
from dotenv import dotenv_values

RAIZ = Path(__file__).resolve().parents[2]
PASTA_MIGRATIONS_SQL = RAIZ / "supabase" / "migrations"
BOOTSTRAP = Path(__file__).resolve().parent / "bootstrap_supabase.sql"
VARIAVEL_URL = "TEST_DATABASE_URL"
HOSTS_LOCAIS = frozenset({"localhost", "127.0.0.1", "::1"})
SUFIXO_BANCO_DE_TESTE = "_teste"


def url_de_teste_segura(arquivo_env: Path | None = RAIZ / ".env") -> str | None:
    """TEST_DATABASE_URL do ambiente (ou, na falta, do .env), so se for local e de teste."""
    url = os.environ.get(VARIAVEL_URL)
    if not url and arquivo_env is not None and arquivo_env.exists():
        url = dotenv_values(arquivo_env).get(VARIAVEL_URL)
    if not url:
        return None
    partes = urlsplit(url)
    if partes.hostname not in HOSTS_LOCAIS:
        raise RuntimeError(
            f"{VARIAVEL_URL} deve apontar para um banco local (localhost ou 127.0.0.1); "
            "os testes de banco nunca rodam contra o Supabase remoto"
        )
    if not partes.path.lstrip("/").endswith(SUFIXO_BANCO_DE_TESTE):
        raise RuntimeError(
            f"o banco de {VARIAVEL_URL} deve ter nome terminado em '{SUFIXO_BANCO_DE_TESTE}': "
            "os testes recriam o schema public dele"
        )
    return url


@pytest.fixture(scope="session")
def url_banco() -> str:
    url = url_de_teste_segura()
    if url is None:
        pytest.skip(f"{VARIAVEL_URL} nao definida: testes de banco ignorados")
    return url


def rodar_alembic(url: str, *argumentos: str) -> None:
    """Roda o alembic SEMPRE com DATABASE_URL apontando para o banco de teste."""
    resultado = subprocess.run(
        [sys.executable, "-m", "alembic", *argumentos],
        cwd=RAIZ,
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        text=True,
    )
    if resultado.returncode != 0:
        pytest.fail(f"alembic {' '.join(argumentos)} falhou:\n{resultado.stderr}")


@pytest.fixture(scope="session")
def banco_migrado(url_banco: str) -> str:
    with psycopg.connect(url_banco, autocommit=True) as conexao:
        conexao.execute("DROP SCHEMA IF EXISTS public CASCADE")
        conexao.execute("DROP SCHEMA IF EXISTS auth CASCADE")
        conexao.execute("DROP SCHEMA IF EXISTS realtime CASCADE")
        conexao.execute("CREATE SCHEMA public")
        conexao.execute(BOOTSTRAP.read_text(encoding="utf-8"))
        for arquivo in sorted(PASTA_MIGRATIONS_SQL.glob("*.sql")):
            conexao.execute(arquivo.read_text(encoding="utf-8"))
    rodar_alembic(url_banco, "upgrade", "head")
    return url_banco


@pytest.fixture
def conn(banco_migrado: str):
    """Conexao com transacao aberta; tudo que o teste fizer e desfeito no fim."""
    with psycopg.connect(banco_migrado) as conexao:
        yield conexao
        conexao.rollback()


@pytest.fixture
def fab(conn):
    from tests.banco.fabrica import Fabrica

    return Fabrica(conn)


@pytest.fixture
def sa_conn(banco_migrado: str):
    """Conexao SQLAlchemy (a mesma que a API usa) com transacao desfeita no fim do teste."""
    from sqlalchemy import create_engine

    from app.core.db import _url_sqlalchemy

    engine = create_engine(_url_sqlalchemy(banco_migrado))
    with engine.connect() as conexao:
        yield conexao
        conexao.rollback()
    engine.dispose()


@pytest.fixture
def fab_sa(sa_conn):
    """Fabrica que grava na MESMA transacao da `sa_conn`, para a consulta enxergar os dados."""
    from tests.banco.fabrica import Fabrica

    return Fabrica(sa_conn.connection.driver_connection)
