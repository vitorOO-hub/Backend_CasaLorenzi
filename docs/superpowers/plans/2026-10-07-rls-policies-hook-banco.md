# RLS, policies e hook de claims no banco (Alembic) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Proteger o banco com RLS explícito, privilégios mínimos, funções auxiliares, hook de claims (`papel` e `loja_id`) e policies por papel e por loja, tudo em revisões Alembic, validado por testes contra um Postgres **local** (instalado no Windows, banco dedicado `lorenzi_teste`).

**Architecture:** Cinco revisões Alembic encadeadas (escritas à mão com `op.execute`) sobre o `head` atual `20261006213000`: (A) `atendimento.id_loja`, (B) RLS + privilégios + funções auxiliares, (C) hook de claims, (D1) policies de atendimento, (D2) policies de pedidos e estoque. Os testes sobem o schema do Supabase num Postgres de teste (papéis `anon`/`authenticated`, schema `auth` com `uid()`/`jwt()`), aplicam os 3 SQLs de `supabase/migrations/` e o `alembic upgrade head`, e provam as policies trocando de papel (`SET LOCAL ROLE`) com claims injetadas.

**Tech Stack:** Alembic 1.x (`op.execute`), PostgreSQL 15 ou superior instalado localmente, psycopg 3, pytest, python-dotenv.

**Spec:** `docs/superpowers/specs/2026-10-06-auth-rls-sobre-intermediaria-design.md`, seções "2. Banco" e "3. Testes". Refinamento em relação ao spec: a revisão única vira **5 revisões encadeadas** (uma por responsabilidade, com `downgrade` próprio). O efeito é o mesmo, porque o `alembic/env.py` aplica `upgrade head` numa única transação (DDL transacional do Postgres: tudo ou nada).

## Global Constraints

- **NENHUMA requisição a serviço externo e nenhuma conexão ao banco remoto do Supabase.** O usuário pediu: "não faça nenhuma requisição ainda". Todo comando `alembic` deste plano roda **com `DATABASE_URL` definida explicitamente para o Postgres local de teste** (o `.env` aponta para o banco remoto e nunca pode ser usado). `alembic upgrade head` no banco remoto **não faz parte deste plano**: só depois de autorização explícita do usuário, fora daqui.
- **Fluxo de git:** trabalhar na branch `feat/rls-policies-banco`, criada a partir de `feat/rls-policies-auth`. **Não fazer push, merge nem fetch.** Não editar arquivos de módulo do outro integrante (`app/admin`, `app/atendimento`, `app/compras`, `app/estoque`, `app/movimentacoes`, `app/core/db.py`, `app/core/repositorio.py`) nem as revisões existentes `alembic/versions/20261005000000_*` e `20261006213000_*`.
- **Sem Docker.** O usuário escolheu um PostgreSQL instalado no Windows. Pré-requisito, feito por ele uma vez: servidor PostgreSQL 15 ou superior rodando em `localhost:5432`, um banco **dedicado** chamado `lorenzi_teste` (`CREATE DATABASE lorenzi_teste;`) e a variável `TEST_DATABASE_URL` (no ambiente ou numa linha do `.env`, que é ignorado pelo git) no formato `postgresql://postgres:<senha>@127.0.0.1:5432/lorenzi_teste`. A senha nunca vai para o git, para logs nem para relatórios. Se o servidor ou a variável não existirem, pare e reporte NEEDS_CONTEXT: o controlador pede ao usuário. **Nenhum download e nenhuma instalação** além do que o usuário já fez.
- **Os testes recriam o schema `public` e o `auth` do banco de teste** (`DROP SCHEMA ... CASCADE`). Por isso a guarda só aceita host local **e** nome de banco terminado em `_teste`; qualquer outro destino é recusado com erro. Os papéis `anon`, `authenticated`, `service_role` e `supabase_auth_admin` são criados no cluster local (nível de servidor), o que é inofensivo.
- Comandos assumem a raiz do repositório, Git Bash e o interpretador `.venv/Scripts/python.exe`. `TEST_DATABASE_URL` vem do ambiente ou do `.env` (o `conftest` lê os dois; o ambiente tem precedência).
- Idioma do domínio: nomes, mensagens e comentários em português, sem acentos em identificadores SQL e Python.
- `down_revision` da primeira revisão nova: `"20261006213000"`. IDs das novas revisões, em ordem: `20261007000000`, `20261007000100`, `20261007000200`, `20261007000300`, `20261007000400`.
- SQL das revisões: **um `op.execute` por comando** (nunca `executar_bloco`, que quebra em `;`), sem `:nome` (SQLAlchemy `text()` leria como parâmetro; `::tipo` é seguro) e sem `%` solto, exceto dentro de `format('%I')` (o `text()` escapa). Linhas de código e SQL com no máximo 100 colunas (ruff E501).
- Papéis válidos nos claims: `atendente`, `operador_estoque`, `gerente_loja`, `admin` (o hook traduz o código `diretor` do banco para `admin`). `atendente`, `operador_estoque` e `gerente_loja` carregam `loja_id`; `admin` e cliente (sem `papel`) não.
- Todas as policies são `TO authenticated`, usam `(SELECT auth.uid())` ou as funções auxiliares, e **nenhuma policy nova existe para `anon`**. Não há policy de `UPDATE` nem `DELETE` em lugar nenhum; `INSERT` direto só em `mensagem` e `avaliacao_atendimento`.
- Commits terminam com a linha `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

---

### Task 1: Infraestrutura de teste com Postgres local

**Files:**
- Create: `tests/banco/__init__.py` (vazio)
- Create: `tests/banco/bootstrap_supabase.sql`
- Create: `tests/banco/conftest.py`
- Create: `tests/banco/apoio.py`
- Create: `tests/banco/test_url_segura.py`
- Create: `tests/banco/test_infra.py`
- Modify: `pytest.ini`
- Modify: `.env.example`

**Interfaces:**
- Produces (`tests/banco/conftest.py`): `url_de_teste_segura(arquivo_env: Path | None = RAIZ / ".env") -> str | None` (lê `TEST_DATABASE_URL` do ambiente e, se faltar, do `.env`; recusa com `RuntimeError` host não local ou banco cujo nome não termine em `_teste`); fixtures `url_banco` (session; pula se a variável faltar), `banco_migrado` (session; recria o schema, aplica bootstrap, os SQLs de `supabase/migrations/` e `alembic upgrade head`; devolve a URL), `conn` (por teste; transação com rollback).
- Produces (`tests/banco/apoio.py`): `como(conn, *, role="authenticated", sub=None, papel=None, loja=None)` (context manager: injeta claims e troca o papel), `tenta(conn, comando, parametros=None)` (executa num savepoint; devolve linhas ou a exceção `psycopg.Error`), `e_erro(resultado, tipo=psycopg.errors.InsufficientPrivilege) -> bool`.

- [ ] **Step 1: Criar a branch de trabalho**

Run: `git switch -c feat/rls-policies-banco && git branch --show-current && git status --short`
Expected: `feat/rls-policies-banco` e árvore limpa.

- [ ] **Step 2: Conferir o pré-requisito (feito pelo usuário, uma vez)**

Este passo só **verifica**; não instale nada e não baixe nada. O usuário já instalou o PostgreSQL, criou o banco `lorenzi_teste` e definiu `TEST_DATABASE_URL` (ambiente ou `.env`). Confirme com um snippet que não imprime a URL nem a senha:

```bash
.venv/Scripts/python.exe -I -c "import os, sys; sys.path.insert(0, '.'); from dotenv import dotenv_values; url = os.environ.get('TEST_DATABASE_URL') or dotenv_values('.env').get('TEST_DATABASE_URL'); print('TEST_DATABASE_URL definida:', bool(url)); import psycopg; conexao = psycopg.connect(url, connect_timeout=5); print('servidor:', conexao.execute('SHOW server_version').fetchone()[0]); print('banco:', conexao.execute('SELECT current_database()').fetchone()[0])"
```
Expected: `TEST_DATABASE_URL definida: True`, a versão do servidor (15 ou superior) e `banco: lorenzi_teste`. Se a variável não existir, o servidor não responder ou o banco não terminar em `_teste`, **pare e reporte NEEDS_CONTEXT** com a mensagem de erro (sem a senha).

- [ ] **Step 3: Criar `tests/banco/bootstrap_supabase.sql`**

```sql
-- Imita o que o Supabase ja entrega no banco hospedado: papeis, schema auth e privilegios padrao.
-- So para o Postgres de teste local; nunca roda no Supabase.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        CREATE ROLE anon NOLOGIN NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        CREATE ROLE authenticated NOLOGIN NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        CREATE ROLE service_role NOLOGIN NOINHERIT BYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'supabase_auth_admin') THEN
        CREATE ROLE supabase_auth_admin NOLOGIN NOINHERIT;
    END IF;
END
$$;

CREATE SCHEMA IF NOT EXISTS auth;

CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid
LANGUAGE sql STABLE AS $$
    SELECT coalesce(
        nullif(current_setting('request.jwt.claim.sub', true), ''),
        (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub')
    )::uuid
$$;

CREATE OR REPLACE FUNCTION auth.jwt() RETURNS jsonb
LANGUAGE sql STABLE AS $$
    SELECT coalesce(
        nullif(current_setting('request.jwt.claim', true), ''),
        nullif(current_setting('request.jwt.claims', true), '')
    )::jsonb
$$;

CREATE OR REPLACE FUNCTION auth.role() RETURNS text
LANGUAGE sql STABLE AS $$
    SELECT coalesce(
        nullif(current_setting('request.jwt.claim.role', true), ''),
        (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role')
    )::text
$$;

GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role, supabase_auth_admin;
GRANT USAGE ON SCHEMA auth TO anon, authenticated, service_role, supabase_auth_admin;
GRANT EXECUTE ON FUNCTION auth.uid(), auth.jwt(), auth.role()
    TO anon, authenticated, service_role, supabase_auth_admin;

-- O Supabase concede tudo por padrao nas tabelas e funcoes novas do schema public.
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    GRANT ALL ON TABLES TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    GRANT ALL ON FUNCTIONS TO anon, authenticated, service_role;
```

- [ ] **Step 4: Criar `tests/banco/__init__.py` (arquivo vazio) e `tests/banco/apoio.py`**

```python
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
```

- [ ] **Step 5: Escrever o teste da guarda de URL (falha primeiro)**

Criar `tests/banco/test_url_segura.py`:

```python
import pytest

from tests.banco.conftest import VARIAVEL_URL, url_de_teste_segura

URL_LOCAL = "postgresql://postgres:senha-local@127.0.0.1:5432/lorenzi_teste"


@pytest.fixture(autouse=True)
def ambiente_limpo(monkeypatch):
    monkeypatch.delenv(VARIAVEL_URL, raising=False)


def test_sem_variavel_devolve_none():
    assert url_de_teste_segura(arquivo_env=None) is None


@pytest.mark.parametrize(
    "url",
    [
        URL_LOCAL,
        "postgresql://postgres:senha-local@localhost:5432/outro_teste",
        "postgresql://postgres:senha-local@[::1]:5432/lorenzi_teste",
    ],
)
def test_aceita_host_local_e_banco_de_teste(monkeypatch, url):
    monkeypatch.setenv(VARIAVEL_URL, url)
    assert url_de_teste_segura(arquivo_env=None) == url


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://postgres:segredo@db.abcdefghijkl.supabase.co:5432/lorenzi_teste",
        "postgresql://postgres.abc:segredo@aws-0-sa-east-1.pooler.supabase.com:6543/postgres",
        "postgresql://postgres:segredo@10.0.0.5:5432/lorenzi_teste",
    ],
)
def test_recusa_host_que_nao_e_local_sem_vazar_a_senha(monkeypatch, url):
    monkeypatch.setenv(VARIAVEL_URL, url)
    with pytest.raises(RuntimeError) as erro:
        url_de_teste_segura(arquivo_env=None)
    assert "segredo" not in str(erro.value)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://postgres:segredo@127.0.0.1:5432/postgres",
        "postgresql://postgres:segredo@localhost:5432/lorenzi",
    ],
)
def test_recusa_banco_cujo_nome_nao_termina_em_teste(monkeypatch, url):
    monkeypatch.setenv(VARIAVEL_URL, url)
    with pytest.raises(RuntimeError) as erro:
        url_de_teste_segura(arquivo_env=None)
    assert "segredo" not in str(erro.value)


def test_le_do_arquivo_env_quando_a_variavel_nao_existe(tmp_path):
    arquivo = tmp_path / ".env"
    arquivo.write_text(f"OUTRA=1
{VARIAVEL_URL}={URL_LOCAL}
", encoding="utf-8")
    assert url_de_teste_segura(arquivo_env=arquivo) == URL_LOCAL


def test_ambiente_tem_precedencia_sobre_o_arquivo_env(monkeypatch, tmp_path):
    arquivo = tmp_path / ".env"
    arquivo.write_text(f"{VARIAVEL_URL}={URL_LOCAL}
", encoding="utf-8")
    do_ambiente = "postgresql://postgres:senha-local@127.0.0.1:5432/ambiente_teste"
    monkeypatch.setenv(VARIAVEL_URL, do_ambiente)
    assert url_de_teste_segura(arquivo_env=arquivo) == do_ambiente


def test_arquivo_env_apontando_para_banco_remoto_tambem_e_recusado(tmp_path):
    arquivo = tmp_path / ".env"
    remoto = "postgresql://postgres:segredo@db.abc.supabase.co:5432/lorenzi_teste"
    arquivo.write_text(f"{VARIAVEL_URL}={remoto}
", encoding="utf-8")
    with pytest.raises(RuntimeError):
        url_de_teste_segura(arquivo_env=arquivo)
```

- [ ] **Step 6: Rodar e ver falhar**

Run: `.venv/Scripts/python.exe -m pytest tests/banco/test_url_segura.py -q`
Expected: FAIL com `ImportError`/`ModuleNotFoundError` (o `conftest.py` ainda não existe).

- [ ] **Step 7: Criar `tests/banco/conftest.py`**

```python
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
```

- [ ] **Step 8: Rodar e ver passar (sem banco ainda)**

Run: `.venv/Scripts/python.exe -m pytest tests/banco/test_url_segura.py -q`
Expected: PASS (12 testes). Nenhum teste de banco é necessário nesta etapa; a guarda é testada sem conectar em nada.

- [ ] **Step 9: Marcador, `.env.example` e teste de infraestrutura**

Em `pytest.ini`, acrescentar ao final:

```ini
markers =
    banco: testes que exigem um Postgres local (TEST_DATABASE_URL); sao pulados sem ele
```

No `.env.example`, acrescentar ao final:

```text
# Postgres LOCAL so para os testes de banco: banco dedicado com nome terminado em _teste.
# Os testes recriam o schema public dele. Nunca aponte para o Supabase.
TEST_DATABASE_URL=postgresql://postgres:preencha_a_senha@127.0.0.1:5432/lorenzi_teste
```

Criar `tests/banco/test_infra.py`:

```python
from uuid import uuid4

import pytest

from tests.banco.apoio import como

pytestmark = pytest.mark.banco


def test_papeis_do_supabase_existem(conn):
    nomes = {
        linha[0]
        for linha in conn.execute(
            "SELECT rolname FROM pg_roles "
            "WHERE rolname IN ('anon', 'authenticated', 'service_role', 'supabase_auth_admin')"
        )
    }
    assert nomes == {"anon", "authenticated", "service_role", "supabase_auth_admin"}


def test_auth_uid_le_o_sub_das_claims(conn):
    sub = uuid4()
    with como(conn, sub=sub):
        assert conn.execute("SELECT auth.uid()").fetchone()[0] == sub


def test_auth_jwt_devolve_as_claims(conn):
    with como(conn, papel="admin"):
        claims = conn.execute("SELECT auth.jwt()").fetchone()[0]
    assert claims["papel"] == "admin"


def test_schema_do_projeto_foi_aplicado(conn):
    tabelas = {
        linha[0]
        for linha in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        )
    }
    assert {"loja", "usuario", "pedido", "estoque", "atendimento", "mensagem"} <= tabelas
    assert conn.execute("SELECT count(*) FROM alembic_version").fetchone()[0] == 1


def test_opcoes_de_dominio_vieram_semeadas(conn):
    tipos = conn.execute(
        "SELECT count(*) FROM tipo_usuario WHERE codigo IN ('cliente', 'diretor')"
    ).fetchone()[0]
    assert tipos == 2
    resolvido = conn.execute(
        "SELECT count(*) FROM status_atendimento WHERE codigo = 'resolvido'"
    ).fetchone()[0]
    assert resolvido == 1
```

- [ ] **Step 10: Rodar os testes de banco no Postgres local**

Run: `.venv/Scripts/python.exe -m pytest tests/banco -q`
Expected: todos passam (12 de `test_url_segura` + 5 de `test_infra`). Na primeira execução o `banco_migrado` recria o schema de `lorenzi_teste`, aplica o bootstrap, os 3 SQLs de `supabase/migrations/` e o `alembic upgrade head`; se o `alembic` falhar, o erro aparece em `pytest.fail` com o stderr (sem a senha: confira antes de colar o texto no relatório). Se o Postgres local não responder, **pare e reporte NEEDS_CONTEXT** (não tente iniciar serviços nem instalar nada).

Se `TEST_DATABASE_URL` não estiver definida (nem no ambiente nem no `.env`), os 5 testes de `test_infra` devem ser **pulados** e os 12 de `test_url_segura` passar: `12 passed, 5 skipped`.

- [ ] **Step 11: Lint e commit**

Run: `.venv/Scripts/python.exe -m ruff check tests/banco`
Expected: `All checks passed!`

```bash
git add pytest.ini .env.example tests/banco
git commit -m "test(banco): adiciona Postgres local de teste com schema do Supabase" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Revisão A — `atendimento.id_loja` com trigger, e fábrica de dados

**Files:**
- Create: `alembic/versions/20261007000000_atendimento_id_loja.py`
- Create: `tests/banco/fabrica.py`
- Modify: `tests/banco/conftest.py` (acrescentar a fixture `fab`)
- Create: `tests/banco/test_atendimento_id_loja.py`

**Interfaces:**
- Consumes: `conn`, `banco_migrado` (Task 1); `como`, `tenta` (Task 1).
- Produces (`tests/banco/fabrica.py`): `Usuario(id: UUID, auth: UUID, tipo: str, loja: UUID | None)` (dataclass frozen) e `Fabrica(conn)` com os métodos `loja(*, ativa=True) -> UUID`, `usuario(tipo, *, loja=None, ativo=True) -> Usuario`, `pedido(*, loja, cliente) -> UUID`, `atendimento(*, cliente, loja=None, pedido=None, status="aberto") -> UUID`, `mensagem(*, atendimento, remetente, texto="ola") -> UUID`, `variacao() -> UUID`, `estoque(*, loja, variacao=None, quantidade=5) -> UUID`, `item_pedido(*, pedido, variacao=None) -> UUID`, `pagamento(*, pedido, valor=10) -> UUID`, `movimentacao(*, loja, variacao=None) -> UUID`. Fixture `fab(conn) -> Fabrica`.
- Produces (banco): coluna `atendimento.id_loja uuid` nullable, FK `fk_atendimento_loja`, índice `idx_atendimento_id_loja`, função `public.preencher_id_loja_atendimento()` e trigger `trg_atendimento_preencher_id_loja` (BEFORE INSERT).

- [ ] **Step 1: Criar `tests/banco/fabrica.py`**

```python
"""Fabrica de dados para os testes de banco. Roda como superusuario, antes de trocar de papel."""

from dataclasses import dataclass
from uuid import UUID, uuid4


@dataclass(frozen=True)
class Usuario:
    id: UUID
    auth: UUID
    tipo: str
    loja: UUID | None


class Fabrica:
    def __init__(self, conn) -> None:
        self.conn = conn
        self._contador = 0

    def _proximo(self) -> int:
        self._contador += 1
        return self._contador

    def _um(self, comando: str, parametros: tuple = ()):
        return self.conn.execute(comando, parametros).fetchone()[0]

    def loja(self, *, ativa: bool = True) -> UUID:
        n = self._proximo()
        return self._um(
            "INSERT INTO loja (codigo, nome, ativa) VALUES (%s, %s, %s) RETURNING id_loja",
            (f"L{n}", f"Loja {n}", ativa),
        )

    def usuario(self, tipo: str, *, loja: UUID | None = None, ativo: bool = True) -> Usuario:
        n = self._proximo()
        auth = uuid4()
        id_usuario = self._um(
            """
            INSERT INTO usuario (id_tipo_usuario, id_loja, auth_user_id, nome, email, ativo)
            VALUES (
                (SELECT id_tipo_usuario FROM tipo_usuario WHERE codigo = %s),
                %s, %s, %s, %s, %s
            )
            RETURNING id_usuario
            """,
            (tipo, loja, auth, f"Usuario {n}", f"u{n}@teste.local", ativo),
        )
        return Usuario(id=id_usuario, auth=auth, tipo=tipo, loja=loja)

    def pedido(self, *, loja: UUID, cliente: Usuario) -> UUID:
        n = self._proximo()
        return self._um(
            """
            INSERT INTO pedido (numero_pedido, id_loja, id_cliente, id_status_pedido)
            VALUES (
                %s, %s, %s,
                (SELECT id_status_pedido FROM status_pedido WHERE codigo = 'criado')
            )
            RETURNING id_pedido
            """,
            (f"PD-{n}", loja, cliente.id),
        )

    def atendimento(
        self,
        *,
        cliente: Usuario,
        loja: UUID | None = None,
        pedido: UUID | None = None,
        status: str = "aberto",
    ) -> UUID:
        return self._um(
            """
            INSERT INTO atendimento (
                id_cliente, id_loja, id_pedido, id_canal_atendimento,
                id_categoria_atendimento, id_prioridade_atendimento, id_status_atendimento
            )
            VALUES (
                %s, %s, %s,
                (SELECT id_canal_atendimento FROM canal_atendimento ORDER BY ordem LIMIT 1),
                (SELECT id_categoria_atendimento FROM categoria_atendimento ORDER BY ordem LIMIT 1),
                (SELECT id_prioridade_atendimento FROM prioridade_atendimento ORDER BY ordem LIMIT 1),
                (SELECT id_status_atendimento FROM status_atendimento WHERE codigo = %s)
            )
            RETURNING id_atendimento
            """,
            (cliente.id, loja, pedido, status),
        )

    def mensagem(self, *, atendimento: UUID, remetente: Usuario, texto: str = "ola") -> UUID:
        return self._um(
            """
            INSERT INTO mensagem (id_atendimento, id_usuario_remetente, texto)
            VALUES (%s, %s, %s)
            RETURNING id_mensagem
            """,
            (atendimento, remetente.id, texto),
        )

    def variacao(self) -> UUID:
        n = self._proximo()
        id_produto = self._um(
            "INSERT INTO produto (nome, preco_base) VALUES (%s, 10) RETURNING id_produto",
            (f"Produto {n}",),
        )
        return self._um(
            """
            INSERT INTO variacao_produto (id_produto, sku, cor, tamanho, preco_venda)
            VALUES (%s, %s, 'azul', 'M', 10)
            RETURNING id_variacao
            """,
            (id_produto, f"SKU-{n}"),
        )

    def estoque(self, *, loja: UUID, variacao: UUID | None = None, quantidade: int = 5) -> UUID:
        variacao = variacao or self.variacao()
        return self._um(
            """
            INSERT INTO estoque (id_loja, id_variacao, quantidade)
            VALUES (%s, %s, %s)
            RETURNING id_estoque
            """,
            (loja, variacao, quantidade),
        )

    def item_pedido(self, *, pedido: UUID, variacao: UUID | None = None) -> UUID:
        variacao = variacao or self.variacao()
        return self._um(
            """
            INSERT INTO item_pedido (id_pedido, id_variacao, quantidade, preco_unitario)
            VALUES (%s, %s, 1, 10)
            RETURNING id_item_pedido
            """,
            (pedido, variacao),
        )

    def pagamento(self, *, pedido: UUID, valor: int = 10) -> UUID:
        return self._um(
            """
            INSERT INTO pagamento (id_pedido, id_metodo_pagamento, id_status_pagamento, valor)
            VALUES (
                %s,
                (SELECT id_metodo_pagamento FROM metodo_pagamento WHERE codigo = 'pix'),
                (SELECT id_status_pagamento FROM status_pagamento WHERE codigo = 'pendente'),
                %s
            )
            RETURNING id_pagamento
            """,
            (pedido, valor),
        )

    def movimentacao(self, *, loja: UUID, variacao: UUID | None = None) -> UUID:
        variacao = variacao or self.variacao()
        return self._um(
            """
            INSERT INTO movimentacao_estoque (
                id_loja, id_variacao, id_tipo_movimentacao_estoque,
                quantidade, quantidade_anterior, quantidade_posterior
            )
            VALUES (
                %s, %s,
                (SELECT id_tipo_movimentacao_estoque FROM tipo_movimentacao_estoque
                 WHERE codigo = 'entrada'),
                1, 0, 1
            )
            RETURNING id_movimentacao_estoque
            """,
            (loja, variacao),
        )
```

Acrescentar ao final de `tests/banco/conftest.py`:

```python
@pytest.fixture
def fab(conn):
    from tests.banco.fabrica import Fabrica

    return Fabrica(conn)
```

- [ ] **Step 2: Escrever os testes que falham**

Criar `tests/banco/test_atendimento_id_loja.py`:

```python
import psycopg
import pytest

from tests.banco.apoio import tenta

pytestmark = pytest.mark.banco


def test_coluna_id_loja_existe_e_aceita_nulo(conn):
    nulo = conn.execute(
        "SELECT is_nullable FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = 'atendimento' AND column_name = 'id_loja'"
    ).fetchone()
    assert nulo == ("YES",)


def test_trigger_preenche_a_loja_a_partir_do_pedido(conn, fab):
    loja = fab.loja()
    cliente = fab.usuario("cliente")
    pedido = fab.pedido(loja=loja, cliente=cliente)
    atendimento = fab.atendimento(cliente=cliente, pedido=pedido)
    gravada = conn.execute(
        "SELECT id_loja FROM atendimento WHERE id_atendimento = %s", (atendimento,)
    ).fetchone()[0]
    assert gravada == loja


def test_loja_informada_e_mantida(conn, fab):
    loja_do_pedido, loja_informada = fab.loja(), fab.loja()
    cliente = fab.usuario("cliente")
    pedido = fab.pedido(loja=loja_do_pedido, cliente=cliente)
    atendimento = fab.atendimento(cliente=cliente, loja=loja_informada, pedido=pedido)
    gravada = conn.execute(
        "SELECT id_loja FROM atendimento WHERE id_atendimento = %s", (atendimento,)
    ).fetchone()[0]
    assert gravada == loja_informada


def test_sem_pedido_a_loja_fica_nula(conn, fab):
    atendimento = fab.atendimento(cliente=fab.usuario("cliente"))
    gravada = conn.execute(
        "SELECT id_loja FROM atendimento WHERE id_atendimento = %s", (atendimento,)
    ).fetchone()[0]
    assert gravada is None


def test_loja_inexistente_e_recusada_pela_fk(conn, fab):
    cliente = fab.usuario("cliente")
    resultado = tenta(
        conn,
        "UPDATE atendimento SET id_loja = gen_random_uuid() WHERE id_atendimento = %s",
        (fab.atendimento(cliente=cliente),),
    )
    assert isinstance(resultado, psycopg.errors.ForeignKeyViolation)
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `.venv/Scripts/python.exe -m pytest tests/banco/test_atendimento_id_loja.py -q`
Expected: FAIL: `fab.atendimento` falha com `UndefinedColumn: column "id_loja" of relation "atendimento" does not exist`.

- [ ] **Step 4: Criar a revisão A**

Criar `alembic/versions/20261007000000_atendimento_id_loja.py`:

```python
"""atendimento.id_loja, preenchido a partir do pedido

Revision ID: 20261007000000
Revises: 20261006213000
Create Date: 2026-10-07 00:00:00

O escopo por loja do atendimento precisa de id_loja. A coluna e nullable porque o
POST /atendimentos atual nao envia loja; o trigger a preenche pelo pedido quando houver.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261007000000"
down_revision: str | Sequence[str] | None = "20261006213000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SUBIDA = (
    "ALTER TABLE public.atendimento ADD COLUMN IF NOT EXISTS id_loja UUID",
    """
    DO $bloco$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_atendimento_loja') THEN
            ALTER TABLE public.atendimento
                ADD CONSTRAINT fk_atendimento_loja
                FOREIGN KEY (id_loja) REFERENCES public.loja (id_loja)
                ON UPDATE CASCADE ON DELETE RESTRICT;
        END IF;
    END
    $bloco$
    """,
    "CREATE INDEX IF NOT EXISTS idx_atendimento_id_loja ON public.atendimento (id_loja)",
    """
    CREATE OR REPLACE FUNCTION public.preencher_id_loja_atendimento()
    RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = public, pg_temp
    AS $fn$
    BEGIN
        IF NEW.id_loja IS NULL AND NEW.id_pedido IS NOT NULL THEN
            SELECT p.id_loja INTO NEW.id_loja
            FROM public.pedido p
            WHERE p.id_pedido = NEW.id_pedido;
        END IF;
        RETURN NEW;
    END
    $fn$
    """,
    "DROP TRIGGER IF EXISTS trg_atendimento_preencher_id_loja ON public.atendimento",
    """
    CREATE TRIGGER trg_atendimento_preencher_id_loja
    BEFORE INSERT ON public.atendimento
    FOR EACH ROW EXECUTE FUNCTION public.preencher_id_loja_atendimento()
    """,
)

DESCIDA = (
    "DROP TRIGGER IF EXISTS trg_atendimento_preencher_id_loja ON public.atendimento",
    "DROP FUNCTION IF EXISTS public.preencher_id_loja_atendimento()",
    "DROP INDEX IF EXISTS public.idx_atendimento_id_loja",
    "ALTER TABLE public.atendimento DROP CONSTRAINT IF EXISTS fk_atendimento_loja",
    "ALTER TABLE public.atendimento DROP COLUMN IF EXISTS id_loja",
)


def upgrade() -> None:
    for comando in SUBIDA:
        op.execute(comando)


def downgrade() -> None:
    for comando in DESCIDA:
        op.execute(comando)
```

- [ ] **Step 5: Rodar e ver passar**

Run: `.venv/Scripts/python.exe -m pytest tests/banco -q`
Expected: PASS em todos os testes de banco (os 5 novos mais os da Task 1). Se `psycopg` reclamar de `%` ou `:` na execução da revisão, ajuste o SQL conforme as Global Constraints e anote em relatório.

- [ ] **Step 6: Lint e commit**

Run: `.venv/Scripts/python.exe -m ruff check alembic/versions/20261007000000_atendimento_id_loja.py tests/banco`
Expected: `All checks passed!`

```bash
git add alembic/versions/20261007000000_atendimento_id_loja.py tests/banco/fabrica.py tests/banco/conftest.py tests/banco/test_atendimento_id_loja.py
git commit -m "feat(banco): adiciona atendimento.id_loja preenchida pelo pedido" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Revisão B — RLS explícito, privilégios mínimos e funções auxiliares

**Files:**
- Create: `alembic/versions/20261007000100_rls_privilegios_helpers.py`
- Create: `tests/banco/test_rls_privilegios.py`

**Interfaces:**
- Consumes: `Fabrica`, `Usuario`, fixtures `conn`/`fab`, `como`, `tenta`, `e_erro`.
- Produces (banco): `ENABLE` + `FORCE ROW LEVEL SECURITY` em todas as tabelas de `public` (exceto `alembic_version`); `anon` e `authenticated` sem privilégio em tabelas, exceto `SELECT` em `loja`, `produto`, `variacao_produto` (ambos) e em `metodo_pagamento`, `status_pedido` (só `authenticated`); funções em `public` (todas `STABLE`, `search_path` fixo, `EXECUTE` só para `authenticated`): `app_usuario_id() -> uuid`, `app_papel() -> text`, `app_loja_id() -> uuid`, `app_papel_na_loja(p_loja uuid, p_papeis text[]) -> boolean`, `app_pode_ver_atendimento(p_atendimento uuid) -> boolean`, `app_atendimento_aceita_mensagem(p_atendimento uuid) -> boolean`, `app_pode_avaliar_atendimento(p_atendimento uuid) -> boolean`.

- [ ] **Step 1: Escrever os testes que falham**

Criar `tests/banco/test_rls_privilegios.py`:

```python
from uuid import uuid4

import pytest
from psycopg import sql

from tests.banco.apoio import como, e_erro, tenta
from tests.banco.fabrica import Usuario

pytestmark = pytest.mark.banco

TABELAS_SENSIVEIS = [
    "usuario",
    "atendimento",
    "atendimento_item",
    "mensagem",
    "avaliacao_atendimento",
    "pedido",
    "item_pedido",
    "pagamento",
    "estoque",
    "movimentacao_estoque",
]

ASSINATURAS = [
    "app_usuario_id()",
    "app_papel()",
    "app_loja_id()",
    "app_papel_na_loja(uuid, text[])",
    "app_pode_ver_atendimento(uuid)",
    "app_atendimento_aceita_mensagem(uuid)",
    "app_pode_avaliar_atendimento(uuid)",
]

PRIVILEGIOS_DE_ESCRITA = (
    "('INSERT'), ('UPDATE'), ('DELETE'), ('TRUNCATE'), ('REFERENCES'), ('TRIGGER')"
)


def como_usuario(conn, usuario: Usuario):
    papel = {"diretor": "admin"}.get(usuario.tipo, usuario.tipo)
    papel = None if papel == "cliente" else papel
    loja = None if papel in (None, "admin") else usuario.loja
    return como(conn, sub=usuario.auth, papel=papel, loja=loja)


def test_rls_ligado_e_forcado_em_todas_as_tabelas(conn):
    linhas = conn.execute(
        """
        SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relname <> 'alembic_version'
        """
    ).fetchall()
    assert len(linhas) >= 20
    assert [nome for nome, rls, forca in linhas if not (rls and forca)] == []


@pytest.mark.parametrize("tabela", TABELAS_SENSIVEIS)
def test_anon_nao_le_tabelas_sensiveis(conn, tabela):
    with como(conn, role="anon"):
        resultado = tenta(conn, sql.SQL("SELECT 1 FROM {} LIMIT 1").format(sql.Identifier(tabela)))
    assert e_erro(resultado)


def test_anon_so_tem_privilegio_no_catalogo(conn):
    linhas = conn.execute(
        """
        SELECT c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind = 'r'
          AND has_any_column_privilege('anon', c.oid, 'SELECT, INSERT, UPDATE, REFERENCES')
        """
    ).fetchall()
    assert {linha[0] for linha in linhas} == {"loja", "produto", "variacao_produto"}


def test_anon_ainda_le_o_catalogo_publico(conn, fab):
    ativa = fab.loja()
    fab.loja(ativa=False)
    with como(conn, role="anon"):
        ids = {linha[0] for linha in tenta(conn, "SELECT id_loja FROM loja")}
    assert ids == {ativa}


def test_authenticated_so_escreve_nas_duas_excecoes(conn):
    linhas = conn.execute(
        f"""
        SELECT c.relname, p.priv
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        CROSS JOIN (VALUES {PRIVILEGIOS_DE_ESCRITA}) AS p(priv)
        WHERE n.nspname = 'public' AND c.relkind = 'r'
          AND has_table_privilege('authenticated', c.oid, p.priv)
        """
    ).fetchall()
    assert set(linhas) <= {("mensagem", "INSERT"), ("avaliacao_atendimento", "INSERT")}


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_ninguem_escreve_em_loja(conn, role):
    with como(conn, role=role):
        for comando in (
            "INSERT INTO loja (codigo, nome) VALUES ('X', 'X')",
            "UPDATE loja SET nome = 'Y'",
            "DELETE FROM loja",
        ):
            assert e_erro(tenta(conn, comando))


@pytest.mark.parametrize("assinatura", ASSINATURAS)
def test_funcoes_auxiliares_so_para_authenticated(conn, assinatura):
    consulta = "SELECT has_function_privilege(%s, %s, 'EXECUTE')"
    nome = f"public.{assinatura}"
    assert conn.execute(consulta, ("authenticated", nome)).fetchone()[0] is True
    assert conn.execute(consulta, ("anon", nome)).fetchone()[0] is False


def test_app_usuario_id_so_devolve_usuario_ativo(conn, fab):
    ativo = fab.usuario("cliente")
    inativo = fab.usuario("cliente", ativo=False)
    with como(conn, sub=ativo.auth):
        assert conn.execute("SELECT public.app_usuario_id()").fetchone()[0] == ativo.id
    with como(conn, sub=inativo.auth):
        assert conn.execute("SELECT public.app_usuario_id()").fetchone()[0] is None
    with como(conn, sub=uuid4()):
        assert conn.execute("SELECT public.app_usuario_id()").fetchone()[0] is None


def test_app_papel_e_loja_leem_as_claims(conn):
    loja = uuid4()
    with como(conn, papel="gerente_loja", loja=loja):
        assert conn.execute("SELECT public.app_papel()").fetchone()[0] == "gerente_loja"
        assert conn.execute("SELECT public.app_loja_id()").fetchone()[0] == loja
    with como(conn):
        assert conn.execute("SELECT public.app_papel()").fetchone()[0] is None
        assert conn.execute("SELECT public.app_loja_id()").fetchone()[0] is None


def papel_na_loja(conn, usuario: Usuario, loja, papeis=("gerente_loja",)) -> bool:
    with como_usuario(conn, usuario):
        consulta = "SELECT public.app_papel_na_loja(%s, %s)"
        return conn.execute(consulta, (loja, list(papeis))).fetchone()[0]


def test_app_papel_na_loja_tabela_verdade(conn, fab):
    loja_a, loja_b = fab.loja(), fab.loja()
    gerente = fab.usuario("gerente_loja", loja=loja_a)
    gerente_inativo = fab.usuario("gerente_loja", loja=loja_a, ativo=False)
    operador = fab.usuario("operador_estoque", loja=loja_a)
    admin = fab.usuario("diretor")
    cliente = fab.usuario("cliente")

    assert papel_na_loja(conn, gerente, loja_a) is True
    assert papel_na_loja(conn, gerente, loja_b) is False
    assert papel_na_loja(conn, gerente, None) is False
    assert papel_na_loja(conn, gerente_inativo, loja_a) is False
    assert papel_na_loja(conn, operador, loja_a) is False
    assert papel_na_loja(conn, operador, loja_a, ("operador_estoque", "gerente_loja")) is True
    assert papel_na_loja(conn, admin, loja_a) is True
    assert papel_na_loja(conn, admin, loja_b) is True
    assert papel_na_loja(conn, cliente, loja_a) is False
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/Scripts/python.exe -m pytest tests/banco/test_rls_privilegios.py -q`
Expected: FAIL: RLS não forçado, `anon` com privilégios amplos, funções inexistentes (`UndefinedFunction`).

- [ ] **Step 3: Criar a revisão B**

Criar `alembic/versions/20261007000100_rls_privilegios_helpers.py`:

```python
"""rls explicito, privilegios minimos e funcoes auxiliares das policies

Revision ID: 20261007000100
Revises: 20261007000000
Create Date: 2026-10-07 00:01:00

A API conecta como postgres (BYPASSRLS); RLS e privilegios protegem o acesso direto do front
ao Supabase (PostgREST e Realtime). O downgrade restaura o estado anterior documentado:
RLS ligado sem FORCE, anon com SELECT e authenticated com SELECT/INSERT/UPDATE/DELETE.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261007000100"
down_revision: str | Sequence[str] | None = "20261007000000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ASSINATURAS_FUNCOES = (
    "app_usuario_id()",
    "app_papel()",
    "app_loja_id()",
    "app_papel_na_loja(uuid, text[])",
    "app_pode_ver_atendimento(uuid)",
    "app_atendimento_aceita_mensagem(uuid)",
    "app_pode_avaliar_atendimento(uuid)",
)

LIGAR_RLS_EM_TODAS_AS_TABELAS = """
DO $bloco$
DECLARE
    tabela record;
BEGIN
    FOR tabela IN
        SELECT tablename FROM pg_tables
        WHERE schemaname = 'public' AND tablename <> 'alembic_version'
    LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', tabela.tablename);
        EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', tabela.tablename);
    END LOOP;
END
$bloco$
"""

DESLIGAR_FORCE_EM_TODAS_AS_TABELAS = """
DO $bloco$
DECLARE
    tabela record;
BEGIN
    FOR tabela IN
        SELECT tablename FROM pg_tables
        WHERE schemaname = 'public' AND tablename <> 'alembic_version'
    LOOP
        EXECUTE format('ALTER TABLE public.%I NO FORCE ROW LEVEL SECURITY', tabela.tablename);
    END LOOP;
END
$bloco$
"""

PRIVILEGIOS_SUBIDA = (
    "REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated",
    "ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public "
    "REVOKE ALL ON TABLES FROM anon, authenticated",
    # Catalogo publico e dados de apoio: as policies de leitura ja existem desde a migration SQL.
    "GRANT SELECT ON public.loja, public.produto, public.variacao_produto TO anon, authenticated",
    "GRANT SELECT ON public.metodo_pagamento, public.status_pedido TO authenticated",
)

PRIVILEGIOS_DESCIDA = (
    "GRANT SELECT ON ALL TABLES IN SCHEMA public TO anon",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO authenticated",
    "ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT SELECT ON TABLES TO anon",
    "ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public "
    "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO authenticated",
)

FUNCOES = (
    """
    CREATE OR REPLACE FUNCTION public.app_usuario_id()
    RETURNS uuid
    LANGUAGE sql
    STABLE
    SECURITY DEFINER
    SET search_path = public, pg_temp
    AS $fn$
        SELECT u.id_usuario
        FROM public.usuario u
        WHERE u.auth_user_id = (SELECT auth.uid()) AND u.ativo
        LIMIT 1
    $fn$
    """,
    """
    CREATE OR REPLACE FUNCTION public.app_papel()
    RETURNS text
    LANGUAGE sql
    STABLE
    SET search_path = public, pg_temp
    AS $fn$
        SELECT (SELECT auth.jwt()) ->> 'papel'
    $fn$
    """,
    """
    CREATE OR REPLACE FUNCTION public.app_loja_id()
    RETURNS uuid
    LANGUAGE sql
    STABLE
    SET search_path = public, pg_temp
    AS $fn$
        SELECT NULLIF((SELECT auth.jwt()) ->> 'loja_id', '')::uuid
    $fn$
    """,
    """
    CREATE OR REPLACE FUNCTION public.app_papel_na_loja(p_loja uuid, p_papeis text[])
    RETURNS boolean
    LANGUAGE sql
    STABLE
    SET search_path = public, pg_temp
    AS $fn$
        SELECT COALESCE(
            public.app_usuario_id() IS NOT NULL
            AND (
                public.app_papel() = 'admin'
                OR (
                    public.app_papel() = ANY (p_papeis)
                    AND p_loja IS NOT NULL
                    AND p_loja = public.app_loja_id()
                )
            ),
            false
        )
    $fn$
    """,
    """
    CREATE OR REPLACE FUNCTION public.app_pode_ver_atendimento(p_atendimento uuid)
    RETURNS boolean
    LANGUAGE sql
    STABLE
    SECURITY DEFINER
    SET search_path = public, pg_temp
    AS $fn$
        SELECT EXISTS (
            SELECT 1
            FROM public.atendimento a
            WHERE a.id_atendimento = p_atendimento
              AND (
                  a.id_cliente = public.app_usuario_id()
                  OR public.app_papel_na_loja(a.id_loja, ARRAY['atendente', 'gerente_loja'])
              )
        )
    $fn$
    """,
    """
    CREATE OR REPLACE FUNCTION public.app_atendimento_aceita_mensagem(p_atendimento uuid)
    RETURNS boolean
    LANGUAGE sql
    STABLE
    SECURITY DEFINER
    SET search_path = public, pg_temp
    AS $fn$
        SELECT public.app_pode_ver_atendimento(p_atendimento)
            AND EXISTS (
                SELECT 1
                FROM public.atendimento a
                JOIN public.status_atendimento s
                    ON s.id_status_atendimento = a.id_status_atendimento
                WHERE a.id_atendimento = p_atendimento
                  AND s.codigo IN ('aberto', 'em_andamento', 'aguardando_cliente')
            )
    $fn$
    """,
    """
    CREATE OR REPLACE FUNCTION public.app_pode_avaliar_atendimento(p_atendimento uuid)
    RETURNS boolean
    LANGUAGE sql
    STABLE
    SECURITY DEFINER
    SET search_path = public, pg_temp
    AS $fn$
        SELECT EXISTS (
            SELECT 1
            FROM public.atendimento a
            JOIN public.status_atendimento s
                ON s.id_status_atendimento = a.id_status_atendimento
            WHERE a.id_atendimento = p_atendimento
              AND a.id_cliente = public.app_usuario_id()
              AND s.codigo IN ('resolvido', 'encerrado')
        )
    $fn$
    """,
)


def upgrade() -> None:
    op.execute(LIGAR_RLS_EM_TODAS_AS_TABELAS)
    for comando in PRIVILEGIOS_SUBIDA:
        op.execute(comando)
    for comando in FUNCOES:
        op.execute(comando)
    for assinatura in ASSINATURAS_FUNCOES:
        op.execute(f"REVOKE ALL ON FUNCTION public.{assinatura} FROM PUBLIC, anon")
        op.execute(f"GRANT EXECUTE ON FUNCTION public.{assinatura} TO authenticated")


def downgrade() -> None:
    for assinatura in reversed(ASSINATURAS_FUNCOES):
        op.execute(f"DROP FUNCTION IF EXISTS public.{assinatura}")
    for comando in PRIVILEGIOS_DESCIDA:
        op.execute(comando)
    op.execute(DESLIGAR_FORCE_EM_TODAS_AS_TABELAS)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/Scripts/python.exe -m pytest tests/banco -q`
Expected: PASS em todos. Pontos que costumam falhar na primeira tentativa: (a) `has_any_column_privilege('anon', oid, 'SELECT, INSERT, UPDATE, REFERENCES')` precisa aceitar a lista; se o Postgres reclamar, troque por quatro chamadas `has_table_privilege` combinadas com `OR`; (b) `%I` no `format` deve passar sem erro pelo `op.execute` (o `text()` do SQLAlchemy escapa `%`); se não passar, relate o erro exato em vez de trocar de abordagem sem registrar.

- [ ] **Step 5: Lint e commit**

Run: `.venv/Scripts/python.exe -m ruff check alembic/versions/20261007000100_rls_privilegios_helpers.py tests/banco`
Expected: `All checks passed!`

```bash
git add alembic/versions/20261007000100_rls_privilegios_helpers.py tests/banco/test_rls_privilegios.py
git commit -m "feat(banco): liga RLS, reduz privilegios e cria funcoes auxiliares das policies" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Revisão C — hook de claims do token

**Files:**
- Create: `alembic/versions/20261007000200_hook_claims_token.py`
- Create: `tests/banco/test_hook_claims.py`

**Interfaces:**
- Consumes: `Fabrica`, `conn`, `fab`.
- Produces (banco): `public.hook_claims_token(event jsonb) returns jsonb` (`SECURITY DEFINER`, `search_path` fixo, `EXECUTE` só para `supabase_auth_admin`). Recebe `{"user_id": "<uuid>", "claims": {...}}` e devolve o evento com `claims.papel` (e `claims.loja_id`, exceto para `admin`) preenchidos; remove `papel` e `loja_id` que já viessem no token; cliente, usuário inativo ou inexistente ficam sem `papel`.

- [ ] **Step 1: Escrever os testes que falham**

Criar `tests/banco/test_hook_claims.py`:

```python
import json
from uuid import uuid4

import pytest

pytestmark = pytest.mark.banco

CLAIMS_BASE = {"role": "authenticated", "aud": "authenticated", "exp": 9999999999}


def chamar_hook(conn, auth_user_id, extras=None) -> dict:
    claims = {**CLAIMS_BASE, "sub": str(auth_user_id), **(extras or {})}
    evento = {"user_id": str(auth_user_id), "claims": claims}
    retorno = conn.execute(
        "SELECT public.hook_claims_token(%s::jsonb)", (json.dumps(evento),)
    ).fetchone()[0]
    return retorno["claims"]


def test_gerente_recebe_papel_e_loja(conn, fab):
    loja = fab.loja()
    gerente = fab.usuario("gerente_loja", loja=loja)
    claims = chamar_hook(conn, gerente.auth)
    assert claims["papel"] == "gerente_loja"
    assert claims["loja_id"] == str(loja)


@pytest.mark.parametrize("tipo", ["atendente", "operador_estoque"])
def test_equipe_de_loja_recebe_papel_e_loja(conn, fab, tipo):
    loja = fab.loja()
    usuario = fab.usuario(tipo, loja=loja)
    claims = chamar_hook(conn, usuario.auth)
    assert claims["papel"] == tipo
    assert claims["loja_id"] == str(loja)


def test_diretor_vira_admin_e_nao_leva_loja(conn, fab):
    diretor = fab.usuario("diretor", loja=fab.loja())
    claims = chamar_hook(conn, diretor.auth)
    assert claims["papel"] == "admin"
    assert "loja_id" not in claims


def test_cliente_nao_recebe_papel_nem_loja(conn, fab):
    cliente = fab.usuario("cliente")
    claims = chamar_hook(conn, cliente.auth)
    assert "papel" not in claims
    assert "loja_id" not in claims


def test_usuario_inativo_fica_sem_papel(conn, fab):
    gerente = fab.usuario("gerente_loja", loja=fab.loja(), ativo=False)
    claims = chamar_hook(conn, gerente.auth)
    assert "papel" not in claims
    assert "loja_id" not in claims


def test_usuario_inexistente_fica_sem_papel(conn):
    claims = chamar_hook(conn, uuid4())
    assert "papel" not in claims


def test_atendente_sem_loja_cadastrada_sai_sem_loja(conn, fab):
    atendente = fab.usuario("atendente")
    claims = chamar_hook(conn, atendente.auth)
    assert claims["papel"] == "atendente"
    assert "loja_id" not in claims


def test_claims_padrao_do_token_sao_preservadas(conn, fab):
    cliente = fab.usuario("cliente")
    claims = chamar_hook(conn, cliente.auth)
    assert claims["sub"] == str(cliente.auth)
    assert claims["role"] == "authenticated"
    assert claims["aud"] == "authenticated"
    assert claims["exp"] == 9999999999


def test_papel_e_loja_que_ja_vinham_no_token_sao_descartados(conn, fab):
    cliente = fab.usuario("cliente")
    claims = chamar_hook(conn, cliente.auth, {"papel": "admin", "loja_id": str(uuid4())})
    assert "papel" not in claims
    assert "loja_id" not in claims


@pytest.mark.parametrize(
    ("papel_do_banco", "esperado"),
    [("authenticated", False), ("anon", False), ("supabase_auth_admin", True)],
)
def test_so_o_supabase_auth_admin_executa_o_hook(conn, papel_do_banco, esperado):
    autorizado = conn.execute(
        "SELECT has_function_privilege(%s, 'public.hook_claims_token(jsonb)', 'EXECUTE')",
        (papel_do_banco,),
    ).fetchone()[0]
    assert autorizado is esperado
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/Scripts/python.exe -m pytest tests/banco/test_hook_claims.py -q`
Expected: FAIL com `UndefinedFunction: function public.hook_claims_token(jsonb) does not exist`.

- [ ] **Step 3: Criar a revisão C**

Criar `alembic/versions/20261007000200_hook_claims_token.py`:

```python
"""hook de claims do token (papel e loja_id)

Revision ID: 20261007000200
Revises: 20261007000100
Create Date: 2026-10-07 00:02:00

Custom Access Token Hook do Supabase. A ativacao no painel (Authentication > Hooks) e um
passo manual: sem ela, todo token de equipe sai sem papel.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261007000200"
down_revision: str | Sequence[str] | None = "20261007000100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SUBIDA = (
    """
    CREATE OR REPLACE FUNCTION public.hook_claims_token(event jsonb)
    RETURNS jsonb
    LANGUAGE plpgsql
    STABLE
    SECURITY DEFINER
    SET search_path = public, pg_temp
    AS $fn$
    DECLARE
        v_claims jsonb := coalesce(event -> 'claims', '{}'::jsonb);
        v_papel text;
        v_loja uuid;
    BEGIN
        SELECT
            CASE t.codigo
                WHEN 'diretor' THEN 'admin'
                WHEN 'cliente' THEN NULL
                ELSE t.codigo
            END,
            u.id_loja
        INTO v_papel, v_loja
        FROM public.usuario u
        JOIN public.tipo_usuario t ON t.id_tipo_usuario = u.id_tipo_usuario
        WHERE u.auth_user_id = (event ->> 'user_id')::uuid
          AND u.ativo
          AND t.ativo;

        -- Nunca confiar em papel ou loja que ja venham no token.
        v_claims := v_claims - 'papel' - 'loja_id';

        IF v_papel IS NOT NULL THEN
            v_claims := jsonb_set(v_claims, '{papel}', to_jsonb(v_papel));
            IF v_papel <> 'admin' AND v_loja IS NOT NULL THEN
                v_claims := jsonb_set(v_claims, '{loja_id}', to_jsonb(v_loja::text));
            END IF;
        END IF;

        RETURN jsonb_set(event, '{claims}', v_claims);
    END
    $fn$
    """,
    "REVOKE ALL ON FUNCTION public.hook_claims_token(jsonb) FROM PUBLIC, anon, authenticated",
    "GRANT EXECUTE ON FUNCTION public.hook_claims_token(jsonb) TO supabase_auth_admin",
)

DESCIDA = ("DROP FUNCTION IF EXISTS public.hook_claims_token(jsonb)",)


def upgrade() -> None:
    for comando in SUBIDA:
        op.execute(comando)


def downgrade() -> None:
    for comando in DESCIDA:
        op.execute(comando)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/Scripts/python.exe -m pytest tests/banco -q`
Expected: PASS em todos. O `GRANT USAGE ON SCHEMA public TO supabase_auth_admin` já vem do bootstrap de teste; no Supabase real esse papel já tem uso do schema `public`.

- [ ] **Step 5: Lint e commit**

Run: `.venv/Scripts/python.exe -m ruff check alembic/versions/20261007000200_hook_claims_token.py tests/banco`
Expected: `All checks passed!`

```bash
git add alembic/versions/20261007000200_hook_claims_token.py tests/banco/test_hook_claims.py
git commit -m "feat(banco): adiciona hook de claims do token (papel e loja_id)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Revisão D1 — policies de atendimento

**Files:**
- Create: `alembic/versions/20261007000300_policies_atendimento.py`
- Create: `tests/banco/test_policies_atendimento.py`

**Interfaces:**
- Consumes: funções auxiliares da Task 3, `Fabrica`, `como`, `tenta`, `e_erro`, e `como_usuario` (definido em `tests/banco/test_rls_privilegios.py`; **copiar a mesma função** para este arquivo, sem importar de outro teste).
- Produces (banco): `GRANT SELECT` para `authenticated` em `usuario`, `atendimento`, `atendimento_item`, `mensagem`, `avaliacao_atendimento`, `tipo_usuario`, `status_atendimento`, `categoria_atendimento`, `canal_atendimento`, `prioridade_atendimento`; `GRANT INSERT` em `mensagem` e `avaliacao_atendimento`; as policies descritas na tabela do spec para essas tabelas.

- [ ] **Step 1: Escrever os testes que falham**

Criar `tests/banco/test_policies_atendimento.py`:

```python
from types import SimpleNamespace

import psycopg
import pytest

from tests.banco.apoio import como, e_erro, tenta
from tests.banco.fabrica import Usuario

pytestmark = pytest.mark.banco

INSERIR_MENSAGEM = (
    "INSERT INTO mensagem (id_atendimento, id_usuario_remetente, texto) VALUES (%s, %s, 'ola')"
)
INSERIR_AVALIACAO = "INSERT INTO avaliacao_atendimento (id_atendimento, nota) VALUES (%s, 5)"


def como_usuario(conn, usuario: Usuario):
    papel = {"diretor": "admin"}.get(usuario.tipo, usuario.tipo)
    papel = None if papel == "cliente" else papel
    loja = None if papel in (None, "admin") else usuario.loja
    return como(conn, sub=usuario.auth, papel=papel, loja=loja)


def ids_visiveis(conn, usuario: Usuario, consulta: str) -> set:
    with como_usuario(conn, usuario):
        return {linha[0] for linha in conn.execute(consulta).fetchall()}


@pytest.fixture
def cenario(fab):
    loja_a, loja_b = fab.loja(), fab.loja()
    usuarios = {
        "cliente1": fab.usuario("cliente"),
        "cliente2": fab.usuario("cliente"),
        "atendente_a": fab.usuario("atendente", loja=loja_a),
        "gerente_a": fab.usuario("gerente_loja", loja=loja_a),
        "atendente_b": fab.usuario("atendente", loja=loja_b),
        "operador_a": fab.usuario("operador_estoque", loja=loja_a),
        "atendente_a_inativo": fab.usuario("atendente", loja=loja_a, ativo=False),
        "admin": fab.usuario("diretor"),
    }
    c1, c2 = usuarios["cliente1"], usuarios["cliente2"]
    atendimentos = {
        "a1": fab.atendimento(cliente=c1, loja=loja_a),
        "a2": fab.atendimento(cliente=c2, loja=loja_a),
        "a3": fab.atendimento(cliente=c1, loja=loja_b),
        "sem_loja": fab.atendimento(cliente=c1),
        "resolvido": fab.atendimento(cliente=c1, loja=loja_a, status="resolvido"),
    }
    return SimpleNamespace(usuarios=usuarios, atendimentos=atendimentos, lojas=(loja_a, loja_b))


# ---- atendimento ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("quem", "esperado"),
    [
        ("cliente1", {"a1", "a3", "sem_loja", "resolvido"}),
        ("cliente2", {"a2"}),
        ("atendente_a", {"a1", "a2", "resolvido"}),
        ("gerente_a", {"a1", "a2", "resolvido"}),
        ("atendente_b", {"a3"}),
        ("operador_a", set()),
        ("atendente_a_inativo", set()),
        ("admin", {"a1", "a2", "a3", "sem_loja", "resolvido"}),
    ],
)
def test_visibilidade_dos_atendimentos(conn, cenario, quem, esperado):
    visiveis = ids_visiveis(
        conn, cenario.usuarios[quem], "SELECT id_atendimento FROM atendimento"
    )
    assert visiveis == {cenario.atendimentos[nome] for nome in esperado}


def test_anon_nao_ve_atendimentos(conn, cenario):
    with como(conn, role="anon"):
        assert e_erro(tenta(conn, "SELECT id_atendimento FROM atendimento"))


def test_itens_do_atendimento_seguem_a_visibilidade(conn, cenario, fab):
    item_pedido = fab.item_pedido(pedido=fab.pedido(loja=cenario.lojas[0],
                                                    cliente=cenario.usuarios["cliente1"]))
    conn.execute(
        "INSERT INTO atendimento_item (id_atendimento, id_item_pedido) VALUES (%s, %s)",
        (cenario.atendimentos["a1"], item_pedido),
    )
    consulta = "SELECT id_atendimento FROM atendimento_item"
    assert ids_visiveis(conn, cenario.usuarios["cliente1"], consulta) == {
        cenario.atendimentos["a1"]
    }
    assert ids_visiveis(conn, cenario.usuarios["cliente2"], consulta) == set()
    assert ids_visiveis(conn, cenario.usuarios["atendente_b"], consulta) == set()


@pytest.mark.parametrize(
    "comando",
    [
        "UPDATE atendimento SET id_loja = NULL",
        "DELETE FROM atendimento",
        "INSERT INTO atendimento (id_cliente) VALUES (gen_random_uuid())",
        "DELETE FROM mensagem",
        "UPDATE mensagem SET texto = 'x'",
    ],
)
def test_nao_ha_escrita_direta_alem_das_duas_excecoes(conn, cenario, comando):
    with como_usuario(conn, cenario.usuarios["admin"]):
        assert e_erro(tenta(conn, comando))


# ---- usuario e opcoes -----------------------------------------------------------------------


@pytest.mark.parametrize("quem", ["cliente1", "atendente_a", "admin"])
def test_usuario_so_ve_a_propria_linha(conn, cenario, quem):
    usuario = cenario.usuarios[quem]
    assert ids_visiveis(conn, usuario, "SELECT id_usuario FROM usuario") == {usuario.id}


@pytest.mark.parametrize(
    "tabela",
    ["status_atendimento", "categoria_atendimento", "canal_atendimento", "prioridade_atendimento"],
)
def test_opcoes_de_atendimento_so_para_logados(conn, cenario, tabela):
    consulta = f"SELECT 1 FROM {tabela}"
    with como_usuario(conn, cenario.usuarios["cliente1"]):
        assert len(tenta(conn, consulta)) > 0
    with como(conn, role="anon"):
        assert e_erro(tenta(conn, consulta))


# ---- mensagem -------------------------------------------------------------------------------


def test_mensagem_so_e_visivel_para_quem_ve_o_atendimento(conn, cenario, fab):
    a1 = cenario.atendimentos["a1"]
    mensagem = fab.mensagem(atendimento=a1, remetente=cenario.usuarios["cliente1"])
    consulta = "SELECT id_mensagem FROM mensagem"
    for quem, esperado in [
        ("cliente1", {mensagem}),
        ("cliente2", set()),
        ("atendente_a", {mensagem}),
        ("atendente_b", set()),
        ("admin", {mensagem}),
    ]:
        assert ids_visiveis(conn, cenario.usuarios[quem], consulta) == esperado, quem


@pytest.mark.parametrize("quem", ["cliente1", "atendente_a", "gerente_a", "admin"])
def test_pode_enviar_mensagem_em_chamado_aberto_que_ve(conn, cenario, quem):
    usuario = cenario.usuarios[quem]
    with como_usuario(conn, usuario):
        resultado = tenta(conn, INSERIR_MENSAGEM, (cenario.atendimentos["a1"], usuario.id))
    assert resultado == []


@pytest.mark.parametrize("quem", ["cliente2", "atendente_b", "operador_a", "atendente_a_inativo"])
def test_nao_envia_mensagem_em_chamado_que_nao_ve(conn, cenario, quem):
    usuario = cenario.usuarios[quem]
    with como_usuario(conn, usuario):
        resultado = tenta(conn, INSERIR_MENSAGEM, (cenario.atendimentos["a1"], usuario.id))
    assert e_erro(resultado)


def test_nao_envia_mensagem_se_nome_de_outro_usuario(conn, cenario):
    with como_usuario(conn, cenario.usuarios["cliente1"]):
        resultado = tenta(
            conn,
            INSERIR_MENSAGEM,
            (cenario.atendimentos["a1"], cenario.usuarios["cliente2"].id),
        )
    assert e_erro(resultado)


def test_nao_envia_mensagem_em_chamado_resolvido(conn, cenario):
    cliente = cenario.usuarios["cliente1"]
    with como_usuario(conn, cliente):
        resultado = tenta(conn, INSERIR_MENSAGEM, (cenario.atendimentos["resolvido"], cliente.id))
    assert e_erro(resultado)


# ---- avaliacao ------------------------------------------------------------------------------


def test_dono_avalia_chamado_resolvido_uma_unica_vez(conn, cenario):
    cliente = cenario.usuarios["cliente1"]
    resolvido = cenario.atendimentos["resolvido"]
    with como_usuario(conn, cliente):
        assert tenta(conn, INSERIR_AVALIACAO, (resolvido,)) == []
        repetida = tenta(conn, INSERIR_AVALIACAO, (resolvido,))
    assert isinstance(repetida, psycopg.errors.UniqueViolation)


def test_nao_avalia_chamado_ainda_aberto(conn, cenario):
    with como_usuario(conn, cenario.usuarios["cliente1"]):
        resultado = tenta(conn, INSERIR_AVALIACAO, (cenario.atendimentos["a1"],))
    assert e_erro(resultado)


@pytest.mark.parametrize("quem", ["cliente2", "atendente_a", "admin"])
def test_so_o_dono_avalia(conn, cenario, quem):
    with como_usuario(conn, cenario.usuarios[quem]):
        resultado = tenta(conn, INSERIR_AVALIACAO, (cenario.atendimentos["resolvido"],))
    assert e_erro(resultado)


def test_avaliacao_e_visivel_para_dono_e_equipe_da_loja(conn, cenario):
    resolvido = cenario.atendimentos["resolvido"]
    conn.execute("INSERT INTO avaliacao_atendimento (id_atendimento, nota) VALUES (%s, 4)", (resolvido,))
    consulta = "SELECT id_atendimento FROM avaliacao_atendimento"
    assert ids_visiveis(conn, cenario.usuarios["cliente1"], consulta) == {resolvido}
    assert ids_visiveis(conn, cenario.usuarios["atendente_a"], consulta) == {resolvido}
    assert ids_visiveis(conn, cenario.usuarios["atendente_b"], consulta) == set()
    assert ids_visiveis(conn, cenario.usuarios["cliente2"], consulta) == set()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/Scripts/python.exe -m pytest tests/banco/test_policies_atendimento.py -q`
Expected: FAIL: `authenticated` ainda sem `SELECT` nas tabelas (`InsufficientPrivilege` nas consultas dos testes de visibilidade).

- [ ] **Step 3: Criar a revisão D1**

Criar `alembic/versions/20261007000300_policies_atendimento.py`:

```python
"""policies de atendimento, mensagem, avaliacao, usuario e opcoes

Revision ID: 20261007000300
Revises: 20261007000200
Create Date: 2026-10-07 00:03:00

Todas as policies sao TO authenticated. Nao ha policy de UPDATE nem DELETE: escrita so pela
API. O front insere direto apenas mensagem e avaliacao (CLAUDE.md, secao 6).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261007000300"
down_revision: str | Sequence[str] | None = "20261007000200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABELAS_DE_OPCOES = (
    "status_atendimento",
    "categoria_atendimento",
    "canal_atendimento",
    "prioridade_atendimento",
    "tipo_usuario",
)

GRANT_SELECT = (
    "GRANT SELECT ON public.usuario, public.atendimento, public.atendimento_item, "
    "public.mensagem, public.avaliacao_atendimento, public.status_atendimento, "
    "public.categoria_atendimento, public.canal_atendimento, "
    "public.prioridade_atendimento, public.tipo_usuario TO authenticated"
)
GRANT_INSERT = "GRANT INSERT ON public.mensagem, public.avaliacao_atendimento TO authenticated"
REVOKE_TUDO = (
    "REVOKE SELECT ON public.usuario, public.atendimento, public.atendimento_item, "
    "public.mensagem, public.avaliacao_atendimento, public.status_atendimento, "
    "public.categoria_atendimento, public.canal_atendimento, "
    "public.prioridade_atendimento, public.tipo_usuario FROM authenticated",
    "REVOKE INSERT ON public.mensagem, public.avaliacao_atendimento FROM authenticated",
)

# (nome, tabela, corpo da policy)
POLITICAS = (
    (
        "usuario - leitura da propria linha",
        "usuario",
        "FOR SELECT TO authenticated USING (auth_user_id = (SELECT auth.uid()))",
    ),
    (
        "atendimento - leitura por dono ou equipe da loja",
        "atendimento",
        "FOR SELECT TO authenticated USING ("
        "id_cliente = (SELECT public.app_usuario_id()) "
        "OR public.app_papel_na_loja(id_loja, ARRAY['atendente', 'gerente_loja']))",
    ),
    (
        "atendimento_item - leitura por quem ve o atendimento",
        "atendimento_item",
        "FOR SELECT TO authenticated USING (public.app_pode_ver_atendimento(id_atendimento))",
    ),
    (
        "mensagem - leitura por quem ve o atendimento",
        "mensagem",
        "FOR SELECT TO authenticated USING (public.app_pode_ver_atendimento(id_atendimento))",
    ),
    (
        "mensagem - envio do proprio autor em chamado em andamento",
        "mensagem",
        "FOR INSERT TO authenticated WITH CHECK ("
        "id_usuario_remetente = (SELECT public.app_usuario_id()) "
        "AND public.app_atendimento_aceita_mensagem(id_atendimento))",
    ),
    (
        "avaliacao_atendimento - leitura por quem ve o atendimento",
        "avaliacao_atendimento",
        "FOR SELECT TO authenticated USING (public.app_pode_ver_atendimento(id_atendimento))",
    ),
    (
        "avaliacao_atendimento - avaliacao do dono apos resolvido",
        "avaliacao_atendimento",
        "FOR INSERT TO authenticated WITH CHECK ("
        "public.app_pode_avaliar_atendimento(id_atendimento))",
    ),
) + tuple(
    (f"{tabela} - leitura por usuarios logados", tabela, "FOR SELECT TO authenticated USING (ativo)")
    for tabela in TABELAS_DE_OPCOES
)


def upgrade() -> None:
    op.execute(GRANT_SELECT)
    op.execute(GRANT_INSERT)
    for nome, tabela, corpo in POLITICAS:
        op.execute(f'DROP POLICY IF EXISTS "{nome}" ON public.{tabela}')
        op.execute(f'CREATE POLICY "{nome}" ON public.{tabela} {corpo}')


def downgrade() -> None:
    for nome, tabela, _corpo in reversed(POLITICAS):
        op.execute(f'DROP POLICY IF EXISTS "{nome}" ON public.{tabela}')
    for comando in REVOKE_TUDO:
        op.execute(comando)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/Scripts/python.exe -m pytest tests/banco -q`
Expected: PASS em todos. Se algum caso de visibilidade falhar, **corrija a policy ou a função auxiliar na revisão correspondente** (B ou D1), nunca o teste para acomodar um comportamento que deixe um usuário ver o que não deve.

- [ ] **Step 5: Lint e commit**

Run: `.venv/Scripts/python.exe -m ruff check alembic/versions/20261007000300_policies_atendimento.py tests/banco`
Expected: `All checks passed!` (se `ruff` apontar linha longa nos testes, quebre a linha sem mudar a lógica).

```bash
git add alembic/versions/20261007000300_policies_atendimento.py tests/banco/test_policies_atendimento.py
git commit -m "feat(banco): adiciona policies de atendimento, mensagem e avaliacao" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Revisão D2 — policies de pedidos e estoque

**Files:**
- Create: `alembic/versions/20261007000400_policies_pedidos_estoque.py`
- Create: `tests/banco/test_policies_pedidos_estoque.py`

**Interfaces:**
- Consumes: `app_papel_na_loja`, `app_usuario_id` (Task 3), `Fabrica` (todos os métodos), `como`, `tenta`, `e_erro`.
- Produces (banco): `GRANT SELECT` para `authenticated` em `pedido`, `item_pedido`, `pagamento`, `estoque`, `movimentacao_estoque`, `status_pagamento`, `tipo_movimentacao_estoque`; policies de leitura: `pedido` (dono, ou `atendente`/`gerente_loja`/`operador_estoque` da loja, ou admin), `item_pedido` e `pagamento` (herdam a visibilidade do pedido), `estoque` e `movimentacao_estoque` (`operador_estoque`/`gerente_loja` da loja, ou admin), opções (`ativo`).

- [ ] **Step 1: Escrever os testes que falham**

Criar `tests/banco/test_policies_pedidos_estoque.py`:

```python
from types import SimpleNamespace

import pytest

from tests.banco.apoio import como, e_erro, tenta
from tests.banco.fabrica import Usuario

pytestmark = pytest.mark.banco


def como_usuario(conn, usuario: Usuario):
    papel = {"diretor": "admin"}.get(usuario.tipo, usuario.tipo)
    papel = None if papel == "cliente" else papel
    loja = None if papel in (None, "admin") else usuario.loja
    return como(conn, sub=usuario.auth, papel=papel, loja=loja)


def ids_visiveis(conn, usuario: Usuario, consulta: str) -> set:
    with como_usuario(conn, usuario):
        return {linha[0] for linha in conn.execute(consulta).fetchall()}


@pytest.fixture
def cenario(fab):
    loja_a, loja_b = fab.loja(), fab.loja()
    usuarios = {
        "cliente1": fab.usuario("cliente"),
        "cliente2": fab.usuario("cliente"),
        "atendente_a": fab.usuario("atendente", loja=loja_a),
        "gerente_a": fab.usuario("gerente_loja", loja=loja_a),
        "operador_a": fab.usuario("operador_estoque", loja=loja_a),
        "operador_b": fab.usuario("operador_estoque", loja=loja_b),
        "operador_a_inativo": fab.usuario("operador_estoque", loja=loja_a, ativo=False),
        "admin": fab.usuario("diretor"),
    }
    c1, c2 = usuarios["cliente1"], usuarios["cliente2"]
    pedidos = {
        "p1": fab.pedido(loja=loja_a, cliente=c1),
        "p2": fab.pedido(loja=loja_a, cliente=c2),
        "p3": fab.pedido(loja=loja_b, cliente=c1),
    }
    itens = {"i1": fab.item_pedido(pedido=pedidos["p1"]), "i2": fab.item_pedido(pedido=pedidos["p2"])}
    pagamentos = {"g1": fab.pagamento(pedido=pedidos["p1"]), "g2": fab.pagamento(pedido=pedidos["p2"])}
    estoques = {"e_a": fab.estoque(loja=loja_a), "e_b": fab.estoque(loja=loja_b)}
    movimentacoes = {"m_a": fab.movimentacao(loja=loja_a), "m_b": fab.movimentacao(loja=loja_b)}
    return SimpleNamespace(
        usuarios=usuarios,
        pedidos=pedidos,
        itens=itens,
        pagamentos=pagamentos,
        estoques=estoques,
        movimentacoes=movimentacoes,
    )


def esperados(mapa: dict, nomes: set) -> set:
    return {mapa[nome] for nome in nomes}


@pytest.mark.parametrize(
    ("quem", "nomes"),
    [
        ("cliente1", {"p1", "p3"}),
        ("cliente2", {"p2"}),
        ("atendente_a", {"p1", "p2"}),
        ("gerente_a", {"p1", "p2"}),
        ("operador_a", {"p1", "p2"}),
        ("operador_b", {"p3"}),
        ("operador_a_inativo", set()),
        ("admin", {"p1", "p2", "p3"}),
    ],
)
def test_visibilidade_dos_pedidos(conn, cenario, quem, nomes):
    visiveis = ids_visiveis(conn, cenario.usuarios[quem], "SELECT id_pedido FROM pedido")
    assert visiveis == esperados(cenario.pedidos, nomes)


@pytest.mark.parametrize(
    ("quem", "nomes"),
    [
        ("cliente1", {"i1"}),
        ("cliente2", {"i2"}),
        ("atendente_a", {"i1", "i2"}),
        ("operador_b", set()),
        ("admin", {"i1", "i2"}),
    ],
)
def test_itens_do_pedido_herdam_a_visibilidade_do_pedido(conn, cenario, quem, nomes):
    visiveis = ids_visiveis(
        conn, cenario.usuarios[quem], "SELECT id_item_pedido FROM item_pedido"
    )
    assert visiveis == esperados(cenario.itens, nomes)


@pytest.mark.parametrize(
    ("quem", "nomes"),
    [
        ("cliente1", {"g1"}),
        ("cliente2", {"g2"}),
        ("gerente_a", {"g1", "g2"}),
        ("operador_b", set()),
        ("admin", {"g1", "g2"}),
    ],
)
def test_pagamentos_herdam_a_visibilidade_do_pedido(conn, cenario, quem, nomes):
    visiveis = ids_visiveis(conn, cenario.usuarios[quem], "SELECT id_pagamento FROM pagamento")
    assert visiveis == esperados(cenario.pagamentos, nomes)


@pytest.mark.parametrize(
    ("quem", "nomes"),
    [
        ("operador_a", {"e_a"}),
        ("gerente_a", {"e_a"}),
        ("operador_b", {"e_b"}),
        ("atendente_a", set()),
        ("cliente1", set()),
        ("operador_a_inativo", set()),
        ("admin", {"e_a", "e_b"}),
    ],
)
def test_visibilidade_do_estoque(conn, cenario, quem, nomes):
    visiveis = ids_visiveis(conn, cenario.usuarios[quem], "SELECT id_estoque FROM estoque")
    assert visiveis == esperados(cenario.estoques, nomes)


@pytest.mark.parametrize(
    ("quem", "nomes"),
    [
        ("operador_a", {"m_a"}),
        ("gerente_a", {"m_a"}),
        ("operador_b", {"m_b"}),
        ("atendente_a", set()),
        ("cliente1", set()),
        ("admin", {"m_a", "m_b"}),
    ],
)
def test_visibilidade_das_movimentacoes(conn, cenario, quem, nomes):
    visiveis = ids_visiveis(
        conn,
        cenario.usuarios[quem],
        "SELECT id_movimentacao_estoque FROM movimentacao_estoque",
    )
    assert visiveis == esperados(cenario.movimentacoes, nomes)


@pytest.mark.parametrize(
    "tabela",
    ["pedido", "item_pedido", "pagamento", "estoque", "movimentacao_estoque"],
)
def test_anon_nao_le_pedidos_nem_estoque(conn, cenario, tabela):
    with como(conn, role="anon"):
        assert e_erro(tenta(conn, f"SELECT 1 FROM {tabela} LIMIT 1"))


@pytest.mark.parametrize(
    "comando",
    [
        "INSERT INTO estoque (id_loja, id_variacao) VALUES (gen_random_uuid(), gen_random_uuid())",
        "UPDATE estoque SET quantidade = 999",
        "DELETE FROM pedido",
        "UPDATE pedido SET valor_total = 0",
        "DELETE FROM movimentacao_estoque",
    ],
)
def test_nao_ha_escrita_direta_em_pedidos_e_estoque(conn, cenario, comando):
    with como_usuario(conn, cenario.usuarios["admin"]):
        assert e_erro(tenta(conn, comando))


@pytest.mark.parametrize("tabela", ["status_pagamento", "tipo_movimentacao_estoque"])
def test_opcoes_de_pedido_so_para_logados(conn, cenario, tabela):
    consulta = f"SELECT 1 FROM {tabela}"
    with como_usuario(conn, cenario.usuarios["cliente1"]):
        assert len(tenta(conn, consulta)) > 0
    with como(conn, role="anon"):
        assert e_erro(tenta(conn, consulta))
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/Scripts/python.exe -m pytest tests/banco/test_policies_pedidos_estoque.py -q`
Expected: FAIL: `InsufficientPrivilege` nas consultas de visibilidade (sem `GRANT SELECT` ainda).

- [ ] **Step 3: Criar a revisão D2**

Criar `alembic/versions/20261007000400_policies_pedidos_estoque.py`:

```python
"""policies de leitura de pedidos, itens, pagamentos, estoque e movimentacoes

Revision ID: 20261007000400
Revises: 20261007000300
Create Date: 2026-10-07 00:04:00

Somente leitura. Item e pagamento herdam a visibilidade do pedido (a subconsulta passa pela
policy de pedido do proprio usuario).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261007000400"
down_revision: str | Sequence[str] | None = "20261007000300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GRANT_SELECT = (
    "GRANT SELECT ON public.pedido, public.item_pedido, public.pagamento, public.estoque, "
    "public.movimentacao_estoque, public.status_pagamento, "
    "public.tipo_movimentacao_estoque TO authenticated"
)
REVOKE_SELECT = (
    "REVOKE SELECT ON public.pedido, public.item_pedido, public.pagamento, public.estoque, "
    "public.movimentacao_estoque, public.status_pagamento, "
    "public.tipo_movimentacao_estoque FROM authenticated"
)

PAPEIS_DO_PEDIDO = "ARRAY['atendente', 'gerente_loja', 'operador_estoque']"
PAPEIS_DO_ESTOQUE = "ARRAY['operador_estoque', 'gerente_loja']"

# (nome, tabela, corpo da policy)
POLITICAS = (
    (
        "pedido - leitura por dono ou equipe da loja",
        "pedido",
        "FOR SELECT TO authenticated USING ("
        "id_cliente = (SELECT public.app_usuario_id()) "
        f"OR public.app_papel_na_loja(id_loja, {PAPEIS_DO_PEDIDO}))",
    ),
    (
        "item_pedido - leitura por quem ve o pedido",
        "item_pedido",
        "FOR SELECT TO authenticated USING (EXISTS ("
        "SELECT 1 FROM public.pedido p WHERE p.id_pedido = item_pedido.id_pedido))",
    ),
    (
        "pagamento - leitura por quem ve o pedido",
        "pagamento",
        "FOR SELECT TO authenticated USING (EXISTS ("
        "SELECT 1 FROM public.pedido p WHERE p.id_pedido = pagamento.id_pedido))",
    ),
    (
        "estoque - leitura pela equipe de estoque da loja",
        "estoque",
        f"FOR SELECT TO authenticated USING (public.app_papel_na_loja(id_loja, {PAPEIS_DO_ESTOQUE}))",
    ),
    (
        "movimentacao_estoque - leitura pela equipe de estoque da loja",
        "movimentacao_estoque",
        f"FOR SELECT TO authenticated USING (public.app_papel_na_loja(id_loja, {PAPEIS_DO_ESTOQUE}))",
    ),
    (
        "status_pagamento - leitura por usuarios logados",
        "status_pagamento",
        "FOR SELECT TO authenticated USING (ativo)",
    ),
    (
        "tipo_movimentacao_estoque - leitura por usuarios logados",
        "tipo_movimentacao_estoque",
        "FOR SELECT TO authenticated USING (ativo)",
    ),
)


def upgrade() -> None:
    op.execute(GRANT_SELECT)
    for nome, tabela, corpo in POLITICAS:
        op.execute(f'DROP POLICY IF EXISTS "{nome}" ON public.{tabela}')
        op.execute(f'CREATE POLICY "{nome}" ON public.{tabela} {corpo}')


def downgrade() -> None:
    for nome, tabela, _corpo in reversed(POLITICAS):
        op.execute(f'DROP POLICY IF EXISTS "{nome}" ON public.{tabela}')
    op.execute(REVOKE_SELECT)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/Scripts/python.exe -m pytest tests/banco -q`
Expected: PASS em todos os testes de banco. As mesmas regras da Task 5 valem: corrigir policy, não teste.

- [ ] **Step 5: Lint e commit**

Run: `.venv/Scripts/python.exe -m ruff check alembic/versions/20261007000400_policies_pedidos_estoque.py tests/banco`
Expected: `All checks passed!` (quebre linhas longas dos f-strings das policies se `ruff` apontar E501).

```bash
git add alembic/versions/20261007000400_policies_pedidos_estoque.py tests/banco/test_policies_pedidos_estoque.py
git commit -m "feat(banco): adiciona policies de leitura de pedidos e estoque" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Fechamento — cadeia, downgrade, documentação e verificação final

**Files:**
- Create: `tests/banco/test_cadeia_alembic.py`
- Create: `tests/banco/test_zz_downgrade.py`
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-10-06-auth-rls-sobre-intermediaria-design.md`

**Interfaces:**
- Consumes: `rodar_alembic`, `banco_migrado`, `RAIZ` (Task 1).
- Produces: nada novo para outras tarefas; fecha o plano.

- [ ] **Step 1: Escrever o teste da cadeia (não precisa de banco)**

Criar `tests/banco/test_cadeia_alembic.py`:

```python
from alembic.config import Config
from alembic.script import ScriptDirectory

from tests.banco.conftest import RAIZ

NOVAS = [
    "20261007000000",
    "20261007000100",
    "20261007000200",
    "20261007000300",
    "20261007000400",
]


def pasta_de_revisoes() -> ScriptDirectory:
    config = Config(str(RAIZ / "alembic.ini"))
    config.set_main_option("script_location", str(RAIZ / "alembic"))
    return ScriptDirectory.from_config(config)


def test_ha_uma_unica_cabeca_e_e_a_ultima_revisao_nova():
    assert pasta_de_revisoes().get_heads() == [NOVAS[-1]]


def test_as_revisoes_novas_formam_uma_cadeia_linear_sobre_a_do_atendimento():
    pasta = pasta_de_revisoes()
    anterior = "20261006213000"
    for revisao in NOVAS:
        assert pasta.get_revision(revisao).down_revision == anterior
        anterior = revisao
```

- [ ] **Step 2: Escrever o teste de downgrade e reaplicação**

Criar `tests/banco/test_zz_downgrade.py` (o prefixo `zz` faz o arquivo rodar por último, porque o teste mexe no schema da sessão e o restaura no `finally`):

```python
import psycopg
import pytest

from tests.banco.conftest import rodar_alembic

pytestmark = pytest.mark.banco

REVISAO_ANTERIOR = "20261006213000"


def estado(url: str) -> dict:
    with psycopg.connect(url) as conexao:
        coluna = conexao.execute(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'atendimento' "
            "AND column_name = 'id_loja'"
        ).fetchone()[0]
        funcoes = conexao.execute(
            "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'public' AND (p.proname LIKE 'app\\_%' "
            "OR p.proname IN ('hook_claims_token', 'preencher_id_loja_atendimento'))"
        ).fetchone()[0]
        politicas = conexao.execute(
            "SELECT count(*) FROM pg_policies WHERE schemaname = 'public' "
            "AND policyname LIKE '% - %'"
        ).fetchone()[0]
        forcado = conexao.execute(
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relforcerowsecurity"
        ).fetchone()[0]
    return {"coluna": coluna, "funcoes": funcoes, "politicas": politicas, "forcado": forcado}


def test_downgrade_remove_tudo_e_upgrade_reaplica(banco_migrado):
    url = banco_migrado
    antes = estado(url)
    assert antes["coluna"] == 1
    assert antes["funcoes"] == 9  # 7 app_* + hook_claims_token + preencher_id_loja_atendimento
    assert antes["politicas"] == 19  # 12 em D1 (7 + 5 de opcoes) e 7 em D2
    assert antes["forcado"] >= 20
    try:
        rodar_alembic(url, "downgrade", REVISAO_ANTERIOR)
        depois = estado(url)
        assert depois == {"coluna": 0, "funcoes": 0, "politicas": 0, "forcado": 0}
    finally:
        rodar_alembic(url, "upgrade", "head")
    assert estado(url) == antes
```

- [ ] **Step 3: Rodar os dois testes**

Run:
```bash
.venv/Scripts/python.exe -m pytest tests/banco/test_cadeia_alembic.py -q
.venv/Scripts/python.exe -m pytest tests/banco -q
```
Expected: cadeia: 2 passed sem banco. Com banco: tudo passa, e `test_zz_downgrade` é o último a rodar. Contagens esperadas (já fixadas no teste): 9 funções (7 `app_*` + `hook_claims_token` + `preencher_id_loja_atendimento`) e 19 policies com " - " no nome (12 da revisão D1, sendo 7 explícitas + 5 de tabelas de opções, e 7 da D2; as 5 policies antigas do catálogo usam ": " e não entram na conta). Se algum número divergir, **descubra a causa** (policy ou função faltando, ou sobrando) e corrija a revisão; só altere o número no teste se a contagem real estiver comprovadamente certa, e justifique no relatório.

- [ ] **Step 4: Documentar no `README.md`**

Acrescentar ao final do `README.md` uma seção (em português, no estilo das demais):

````markdown
## Banco: RLS, policies e hook de claims

As revisões `20261007000000` a `20261007000400` em `alembic/versions/` adicionam, sobre o schema
existente: `atendimento.id_loja` (preenchida pelo pedido), RLS ligado e forçado em todas as tabelas,
privilégios mínimos para `anon` e `authenticated`, funções auxiliares, o hook de claims
(`public.hook_claims_token`) e as policies de leitura por papel e por loja.

Regras: o front só lê o catálogo público e os dados do próprio usuário ou da própria loja, e só
insere direto `mensagem` e `avaliacao_atendimento`. Toda outra escrita passa pela API (que conecta
com credencial privilegiada e ignora RLS).

### Testar localmente (Postgres de teste, não o Supabase)

Pré-requisito, uma vez: PostgreSQL 15 ou superior instalado e rodando em `localhost`, um banco
dedicado `CREATE DATABASE lorenzi_teste;` e a variável `TEST_DATABASE_URL` (no ambiente ou numa
linha do `.env`, que o git ignora):

```text
TEST_DATABASE_URL=postgresql://postgres:<senha>@127.0.0.1:5432/lorenzi_teste
```

```bash
pytest tests/banco -q
```

Os testes **recriam o schema `public` e o `auth`** desse banco a cada execução. Por isso a variável
só é aceita se o host for `localhost`/`127.0.0.1` **e** o nome do banco terminar em `_teste`;
qualquer outro destino (como o Supabase remoto) faz os testes falharem de propósito. Sem a
variável, os testes de banco são pulados.

### Aplicar no banco do Supabase (passo manual, com cuidado)

O banco remoto é compartilhado. Antes de rodar `alembic upgrade head` nele:

1. Avise quem mais usa o banco: `authenticated` deixa de escrever direto nas tabelas (só
   `mensagem` e `avaliacao_atendimento`) e passa a enxergar só o que as policies liberam.
   A API não é afetada.
2. Rode com a `DATABASE_URL` da conexão **direta** (porta 5432), não a do pooler.
3. Ative o hook em Authentication → Hooks → Custom Access Token → função
   `public.hook_claims_token`. Sem isso, os tokens de equipe saem sem `papel`.
4. `atendente`, `operador_estoque` e `gerente_loja` precisam de `usuario.id_loja` preenchida; sem
   loja, o token sai sem `loja_id` e a API responde 401.

Para desfazer: `alembic downgrade 20261006213000` (restaura RLS sem `FORCE` e os privilégios
anteriores).
````

No spec `docs/superpowers/specs/2026-10-06-auth-rls-sobre-intermediaria-design.md`, na seção "2. Banco: uma revisão Alembic nova", acrescentar logo abaixo do título uma linha:

```markdown
> Implementada como cinco revisões encadeadas (`20261007000000` a `20261007000400`), uma por responsabilidade; o `upgrade head` continua atômico (uma transação).
```

- [ ] **Step 5: Verificação final**

Run:
```bash
.venv/Scripts/python.exe -m ruff check alembic/versions/20261007000000_atendimento_id_loja.py alembic/versions/20261007000100_rls_privilegios_helpers.py alembic/versions/20261007000200_hook_claims_token.py alembic/versions/20261007000300_policies_atendimento.py alembic/versions/20261007000400_policies_pedidos_estoque.py tests/banco
.venv/Scripts/python.exe -m pytest -q
git status --short
git diff --stat 36b8846..HEAD -- app alembic/versions/20261005000000_baseline_supabase_sql.py alembic/versions/20261006213000_criar_tabelas_atendimento.py
```
Expected: `ruff` limpo; a suíte inteira passa (os 181 testes anteriores continuam passando, mais os de `tests/banco`; se `TEST_DATABASE_URL` não estiver definida, os testes de banco aparecem como `skipped`); `git status` limpo; o último `git diff --stat` **vazio** (nenhum arquivo de `app/` nem as revisões do outro integrante foram alterados).


- [ ] **Step 6: Commit**

```bash
git add tests/banco/test_cadeia_alembic.py tests/banco/test_zz_downgrade.py README.md docs/superpowers/specs/2026-10-06-auth-rls-sobre-intermediaria-design.md
git commit -m "test(banco): valida cadeia, downgrade e documenta a aplicacao das revisoes" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

## Self-Review (feito ao escrever o plano)

**Cobertura do spec, seções "2. Banco" e "3. Testes":**
- RLS explícito (`ENABLE` + `FORCE`) em todas as tabelas, sem depender do `ensure_rls`: Task 3.
- Privilégios mínimos (`REVOKE ALL`, `GRANT` só do necessário, `ALTER DEFAULT PRIVILEGES`): Tasks 3, 5 e 6.
- Funções auxiliares `SECURITY DEFINER`, `search_path` fixo, `EXECUTE` só para `authenticated` (usuário a partir de `auth.uid()`, papel e loja das claims, "pode ver este atendimento"): Task 3.
- Hook de claims (`diretor` → `admin`, cliente sem `papel`, inativo sem `papel`, `EXECUTE` só para `supabase_auth_admin`): Task 4. A ativação manual no painel fica no README (Task 7).
- `atendimento.id_loja` nullable, FK, índice e trigger a partir do pedido: Task 2.
- Policies da tabela do spec: `usuario`, `atendimento`, `atendimento_item`, `mensagem`, `avaliacao_atendimento` (Task 5); `pedido`, `item_pedido`, `pagamento`, `estoque`, `movimentacao_estoque` (Task 6); tabelas de opções (Tasks 5 e 6). Sem `UPDATE`/`DELETE`: testado.
- `downgrade` completo por revisão e teste de ida e volta: Tasks 2 a 7.
- Postgres real local (instalado no Windows, banco dedicado `lorenzi_teste`), bootstrap dos papéis e do schema `auth`, fixture que aplica os 3 SQLs e o `upgrade head`, transação com rollback, claims injetadas, opt-in por `TEST_DATABASE_URL` com marcador `banco`: Task 1.
- Testes de RLS pedidos no spec: cliente só vê os próprios chamados, atendente de outra loja não vê nada, `anon` sem acesso, mensagem só do autor e em chamado em andamento, avaliação só do dono e só depois de resolvido, nenhuma escrita direta fora das duas exceções, hook devolve as claims certas: Tasks 4 a 6.
- "Aplicação no remoto só com autorização explícita": Global Constraints e README. O plano não roda nada contra o remoto.

**Pontos de atenção:**
- A guarda de URL **falha** (não pula) quando o host não é local, para o `.env` remoto nunca ser usado por engano. Todo `alembic` dos testes recebe `DATABASE_URL` do banco de teste.
- O baseline vazio do outro integrante depende dos 3 SQLs de `supabase/migrations/`; a fixture os aplica em ordem alfabética (que coincide com a cronológica) antes do `upgrade head`.
- A contagem de policies no teste de downgrade (Task 7) deve ser conferida contra o número real ao rodar; o plano manda conferir e justificar, não ajustar às cegas.
- Requer o PostgreSQL local já instalado pelo usuário e um banco dedicado `lorenzi_teste`. O plano não baixa nem instala nada, e não faz nenhuma requisição externa. A guarda de URL só aceita host local e banco terminado em `_teste`, porque os testes recriam o schema `public`.

**Consistência de nomes:** `como`, `tenta`, `e_erro` (Task 1) são usados nas Tasks 3 a 6; `Fabrica` e `Usuario` (Task 2) são usados nas Tasks 3 a 6 com os mesmos nomes de método; `como_usuario` é definida localmente em cada arquivo de teste (Tasks 3, 5 e 6); as assinaturas das funções `app_*` na Task 3 são as mesmas que as policies das Tasks 5 e 6 chamam; os IDs das revisões formam a cadeia `20261006213000 → 20261007000000 → 100 → 200 → 300 → 400`, igual ao teste da Task 7.
