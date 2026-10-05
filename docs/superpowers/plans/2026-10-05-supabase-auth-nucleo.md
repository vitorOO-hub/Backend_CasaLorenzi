# Núcleo de autenticação e sessão Supabase — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O FastAPI aceita o JWT do Supabase Auth, identifica usuário/papel/loja, conecta no Postgres pelo pooler e se protege contra excesso de requisições.

**Architecture:** Login, refresh e logout ficam no Supabase Auth (front com `supabase-js`). O backend valida o access token (ES256 via JWKS com cache e rebusca limitada), expõe `get_current_user` e `requer_papel`, mantém um pool `asyncpg` (que ignora RLS de propósito) e aplica limite global por IP no middleware mais limite por usuário como dependência.

**Tech Stack:** Python 3.12, FastAPI 0.142 (Starlette 1.x), asyncpg, pydantic-settings, PyJWT[crypto], httpx, slowapi/limits; pytest, pytest-asyncio, hypothesis.

**Spec:** `docs/superpowers/specs/2026-10-05-supabase-db-auth-design.md` (local) e `CLAUDE.md` (seções 2, 3, 6, 7, 8, 9).

## Global Constraints

- Identificadores, rotas e mensagens de erro em pt-BR, sem acentos em identificadores; mensagens com acento.
- Mensagens exatas: 401 `Token inválido ou expirado` (com `WWW-Authenticate: Bearer`), 403 `Sem permissão para esta ação`, 503 `Serviço de autenticação indisponível`, 503 `Banco de dados indisponível`, 429 `Muitas requisições. Tente novamente em instantes.` (com `Retry-After`).
- JWT: só `ES256`; `aud="authenticated"`; `iss=<SUPABASE_URL>/auth/v1`; exige `exp`, `iat`, `sub`, `aud`, `iss`; `role == "authenticated"`; `is_anonymous` não pode ser `true`; token ASCII de até 8 KB.
- `papel` ∈ {`atendente`, `operador_estoque`, `gerente_loja`, `admin`} ou ausente (cliente). `loja_id` inteiro obrigatório para papéis internos não admin; nulo para admin e cliente.
- Nunca aceitar `papel`, `id_loja`, `loja_id` ou `id_cliente` em modelos de entrada (exceto rotas admin listadas explicitamente no teste de guarda).
- asyncpg com `statement_cache_size=0` (pooler em modo transação, porta 6543); queries com `$1, $2`, nunca f-string.
- Segredos (`DATABASE_URL`) nunca em log, `repr` ou mensagem de erro.
- Não criar rotas de login/logout, `/me`, migrations ou hook de claims nesta entrega.
- Rodar comandos com o Python da `.venv`: `.venv/Scripts/python -m ...` (Windows, Git Bash).
- Commits no padrão `<tipo>(<escopo>): <descrição>`, terminando com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Não incluir `CLAUDE.md` nem `.gitignore` (alterações do usuário) nos commits.

## Mapa de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `requirements.txt`, `requirements-dev.txt` | dependências |
| `pyproject.toml` | pytest, coverage, ruff |
| `.env.example` | variáveis esperadas, sem valores reais |
| `app/core/config.py` | `Settings`, `get_settings` |
| `app/core/security.py` | `Papel`, `UsuarioAtual`, `usuario_de_claims`, `CacheJWKS`, `ValidadorToken`, `get_current_user`, `requer_papel` |
| `app/core/db.py` | `criar_pool`, `get_pool`, `get_conexao`, `get_transacao`, `router_saude` (`GET /health`) |
| `app/core/limite_requisicoes.py` | `configurar_limites`, `chave_por_ip`, `limite_por_usuario` |
| `app/main.py` | `criar_app` (lifespan, CORS, limites, rotas) |
| `tests/apoio.py` | chaves/tokens de teste, JWKS simulado, relógio, pool falso, settings de teste |
| `tests/conftest.py` | fixtures compartilhadas |
| `tests/unit/`, `tests/seguranca/`, `tests/api/`, `tests/live/` | testes por tipo |

---

### Task 1: Base do projeto e configuração

**Files:**
- Create: `requirements.txt`, `requirements-dev.txt`, `pyproject.toml`, `.env.example`
- Create: `app/__init__.py`, `app/core/__init__.py` (vazios)
- Create: `app/core/config.py`
- Create: `tests/__init__.py`, `tests/unit/__init__.py`, `tests/seguranca/__init__.py`, `tests/api/__init__.py`, `tests/live/__init__.py` (vazios)
- Create: `tests/apoio.py` (só `settings_de_teste` nesta task)
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Produces: `Settings` com `database_url: SecretStr`, `supabase_url: str`, `cors_origins: list[str]`, `limite_padrao: str`, `limite_armazenamento: str`, `db_pool_max: int`, propriedades `supabase_issuer`, `supabase_jwks_url`; `get_settings() -> Settings`; `tests.apoio.settings_de_teste(**sobrescrever) -> Settings`, `tests.apoio.ISSUER`, `tests.apoio.JWKS_URL`.

- [ ] **Step 1: Criar arquivos de dependências e configuração de ferramentas**

`requirements.txt`:
```
fastapi>=0.142
uvicorn[standard]>=0.35
asyncpg>=0.31
pydantic-settings>=2.15
pyjwt[crypto]>=2.15
httpx>=0.28
slowapi>=0.1.10
```

`requirements-dev.txt`:
```
-r requirements.txt
pytest>=8.3
pytest-asyncio>=1.0
pytest-cov>=6.0
hypothesis>=6.100
ruff>=0.6
bandit>=1.7
pip-audit>=2.7
```

`pyproject.toml`:
```toml
[project]
name = "casa-lorenzi-backend"
version = "0.1.0"
requires-python = ">=3.12"

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
asyncio_mode = "auto"
addopts = "-m 'not live' --strict-markers"
markers = ["live: testes contra o Supabase real (somente leitura); rode com -m live"]
filterwarnings = ["ignore:Using `httpx` with `starlette.testclient` is deprecated"]

[tool.coverage.run]
source = ["app"]
branch = true

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "S", "ASYNC"]

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S101", "S105", "S106", "S311"]
```

`.env.example`:
```
# Pooler do Supabase em modo transação (porta 6543). Codifique caracteres especiais da senha (%40 para @ etc.).
DATABASE_URL=postgresql://postgres.<ref>:<senha>@aws-0-us-east-1.pooler.supabase.com:6543/postgres
# URL da API do projeto (não é a URL do dashboard).
SUPABASE_URL=https://<ref>.supabase.co
# Origens do front separadas por vírgula.
CORS_ORIGINS=http://localhost:5173
LIMITE_PADRAO=120/minute
LIMITE_ARMAZENAMENTO=memory://

# Só para os testes live (opcional). Usuário de teste criado no dashboard do Supabase.
SUPABASE_PUBLISHABLE_KEY=
TEST_USER_EMAIL=
TEST_USER_PASSWORD=
```

- [ ] **Step 2: Instalar dependências**

Run: `.venv/Scripts/python -m pip install -r requirements-dev.txt`
Expected: instalação sem erro; `.venv/Scripts/python -c "import fastapi, asyncpg, jwt, slowapi"` sem saída.

- [ ] **Step 3: Escrever os testes de configuração (falhando)**

`tests/apoio.py`:
```python
"""Utilitários compartilhados pelos testes."""

from app.core.config import Settings

SUPABASE_URL = "https://ref-teste.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"
JWKS_URL = f"{ISSUER}/.well-known/jwks.json"
DATABASE_URL_TESTE = "postgresql://usuario:senha-de-teste@localhost:6543/postgres"


def settings_de_teste(**sobrescrever: object) -> Settings:
    valores: dict[str, object] = {
        "database_url": DATABASE_URL_TESTE,
        "supabase_url": SUPABASE_URL,
        "cors_origins": ["http://localhost:5173"],
        "limite_padrao": "1000/minute",
    }
    valores.update(sobrescrever)
    return Settings(_env_file=None, **valores)
```

`tests/unit/test_config.py`:
```python
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from tests.apoio import DATABASE_URL_TESTE, settings_de_teste

VARIAVEIS = ["DATABASE_URL", "SUPABASE_URL", "CORS_ORIGINS", "LIMITE_PADRAO", "LIMITE_ARMAZENAMENTO"]


@pytest.fixture(autouse=True)
def ambiente_limpo(monkeypatch):
    for nome in VARIAVEIS:
        monkeypatch.delenv(nome, raising=False)


def test_deriva_issuer_e_jwks_sem_barra_final():
    settings = settings_de_teste(supabase_url="https://abc.supabase.co/")
    assert settings.supabase_url == "https://abc.supabase.co"
    assert settings.supabase_issuer == "https://abc.supabase.co/auth/v1"
    assert settings.supabase_jwks_url == "https://abc.supabase.co/auth/v1/.well-known/jwks.json"


def test_cors_origins_aceita_lista_separada_por_virgula(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://casa-lorenzi.vercel.app/, http://localhost:5173")
    settings = Settings(_env_file=None, database_url=DATABASE_URL_TESTE, supabase_url="https://abc.supabase.co")
    assert settings.cors_origins == ["https://casa-lorenzi.vercel.app", "http://localhost:5173"]


def test_valores_padrao():
    settings = Settings(_env_file=None, database_url=DATABASE_URL_TESTE, supabase_url="https://abc.supabase.co")
    assert settings.limite_padrao == "120/minute"
    assert settings.limite_armazenamento == "memory://"
    assert settings.db_pool_max == 5
    assert settings.cors_origins == []


def test_supabase_url_precisa_ser_https_e_erro_nao_vaza_senha():
    with pytest.raises(ValidationError) as erro:
        settings_de_teste(supabase_url="postgresql://postgres:segredo-real@db.x.supabase.co:5432/postgres")
    assert "SUPABASE_URL" in str(erro.value)
    assert "segredo-real" not in str(erro.value)


def test_database_url_precisa_ser_postgresql_e_erro_nao_vaza_valor():
    with pytest.raises(ValidationError) as erro:
        settings_de_teste(database_url="mysql://root:segredo-real@localhost/db")
    assert "segredo-real" not in str(erro.value)


def test_limite_padrao_invalido_falha_na_inicializacao():
    with pytest.raises(ValidationError):
        settings_de_teste(limite_padrao="muitas por minuto")


def test_variavel_obrigatoria_ausente():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, supabase_url="https://abc.supabase.co")


def test_database_url_nao_aparece_no_repr():
    settings = settings_de_teste()
    assert "senha-de-teste" not in repr(settings)
    assert settings.database_url.get_secret_value() == DATABASE_URL_TESTE
```

- [ ] **Step 4: Rodar e ver falhar**

Run: `.venv/Scripts/python -m pytest tests/unit/test_config.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.core.config'`

- [ ] **Step 5: Implementar `app/core/config.py`**

```python
"""Configuração da aplicação, lida de variáveis de ambiente e do arquivo .env."""

from functools import lru_cache
from typing import Annotated

from limits import parse
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    # hide_input_in_errors: um valor errado (ex.: a string do Postgres no lugar da URL da API)
    # não pode aparecer no log de erro, porque carrega a senha do banco.
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    database_url: SecretStr
    supabase_url: str
    cors_origins: Annotated[list[str], NoDecode] = []
    limite_padrao: str = "120/minute"
    limite_armazenamento: str = "memory://"
    db_pool_max: int = 5

    @field_validator("database_url")
    @classmethod
    def _validar_database_url(cls, valor: SecretStr) -> SecretStr:
        if not valor.get_secret_value().startswith(("postgresql://", "postgres://")):
            raise ValueError("DATABASE_URL deve começar com postgresql://")
        return valor

    @field_validator("supabase_url")
    @classmethod
    def _validar_supabase_url(cls, valor: str) -> str:
        valor = valor.strip().rstrip("/")
        if not valor.startswith("https://"):
            raise ValueError("SUPABASE_URL deve ser a URL da API (https://<ref>.supabase.co)")
        return valor

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _separar_origens(cls, valor: object) -> object:
        if isinstance(valor, str):
            return [origem.strip().rstrip("/") for origem in valor.split(",") if origem.strip()]
        return valor

    @field_validator("limite_padrao")
    @classmethod
    def _validar_limite(cls, valor: str) -> str:
        parse(valor)
        return valor

    @property
    def supabase_issuer(self) -> str:
        return f"{self.supabase_url}/auth/v1"

    @property
    def supabase_jwks_url(self) -> str:
        return f"{self.supabase_issuer}/.well-known/jwks.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 6: Rodar e ver passar**

Run: `.venv/Scripts/python -m pytest tests/unit/test_config.py -v`
Expected: 8 passed. Se `test_limite_padrao_invalido...` falhar porque `parse` levanta algo que não é `ValueError`, envolva em `try/except Exception as exc: raise ValueError("LIMITE_PADRAO inválido") from exc`.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt requirements-dev.txt pyproject.toml app/ tests/
git add -f .env.example
git commit -m "feat(config): configuração do backend via variáveis de ambiente" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
(`-f` porque o `.gitignore` ignora `.env.*`.)

---

### Task 2: Usuário a partir das claims

**Files:**
- Create: `app/core/security.py` (primeira parte)
- Test: `tests/unit/test_usuario.py`

**Interfaces:**
- Produces: `Papel(StrEnum)`; `UsuarioAtual(id: UUID, email: str | None, papel: Papel | None, loja_id: int | None)` (frozen); `TokenInvalido(Exception)`; `AutenticacaoIndisponivel(Exception)`; `usuario_de_claims(claims: dict[str, Any]) -> UsuarioAtual`; constantes `ALGORITMO`, `AUDIENCIA`, `TAMANHO_MAXIMO_TOKEN`, `MENSAGEM_NAO_AUTENTICADO`, `MENSAGEM_SEM_PERMISSAO`, `MENSAGEM_AUTH_INDISPONIVEL`.

- [ ] **Step 1: Escrever os testes (falhando)**

`tests/unit/test_usuario.py`:
```python
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.core.security import Papel, TokenInvalido, UsuarioAtual, usuario_de_claims

SUB = "6f1c3a52-6a4e-4c8e-9a39-0f1f2b6f2f10"


def claims(**extra: object) -> dict[str, object]:
    base: dict[str, object] = {"sub": SUB, "role": "authenticated", "email": "pessoa@exemplo.com"}
    base.update(extra)
    return base


def test_cliente_nao_tem_papel_nem_loja():
    usuario = usuario_de_claims(claims())
    assert usuario == UsuarioAtual(id=UUID(SUB), email="pessoa@exemplo.com", papel=None, loja_id=None)


def test_email_vazio_vira_none():
    assert usuario_de_claims(claims(email="")).email is None


@pytest.mark.parametrize(
    ("papel", "loja_id"),
    [("atendente", 1), ("operador_estoque", 2), ("gerente_loja", 3), ("admin", None)],
)
def test_usuarios_internos_validos(papel, loja_id):
    usuario = usuario_de_claims(claims(papel=papel, loja_id=loja_id))
    assert usuario.papel is Papel(papel)
    assert usuario.loja_id == loja_id


@pytest.mark.parametrize(
    "extra",
    [
        pytest.param({"sub": "nao-e-uuid"}, id="sub-invalido"),
        pytest.param({"role": "anon"}, id="role-anon"),
        pytest.param({"role": "service_role"}, id="role-service"),
        pytest.param({"is_anonymous": True}, id="anonimo"),
        pytest.param({"papel": "superadmin", "loja_id": 1}, id="papel-inexistente"),
        pytest.param({"papel": "gerente_loja"}, id="gerente-sem-loja"),
        pytest.param({"papel": "admin", "loja_id": 1}, id="admin-com-loja"),
        pytest.param({"loja_id": 1}, id="cliente-com-loja"),
        pytest.param({"papel": "gerente_loja", "loja_id": "3"}, id="loja-texto"),
        pytest.param({"papel": "gerente_loja", "loja_id": True}, id="loja-bool"),
        pytest.param({"email": 123}, id="email-nao-texto"),
    ],
)
def test_claims_rejeitadas(extra):
    with pytest.raises(TokenInvalido):
        usuario_de_claims(claims(**extra))


@pytest.mark.parametrize("ausente", ["sub", "role"])
def test_claim_obrigatoria_ausente(ausente):
    dados = claims()
    del dados[ausente]
    with pytest.raises(TokenInvalido):
        usuario_de_claims(dados)


def test_usuario_atual_e_imutavel():
    usuario = usuario_de_claims(claims())
    with pytest.raises(ValidationError):
        usuario.papel = Papel.ADMIN
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/Scripts/python -m pytest tests/unit/test_usuario.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.core.security'`

- [ ] **Step 3: Implementar a primeira parte de `app/core/security.py`**

```python
"""Validação do JWT emitido pelo Supabase Auth e dependências de autenticação."""

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StrictInt, ValidationError, model_validator

ALGORITMO = "ES256"
AUDIENCIA = "authenticated"
TAMANHO_MAXIMO_TOKEN = 8 * 1024

MENSAGEM_NAO_AUTENTICADO = "Token inválido ou expirado"
MENSAGEM_SEM_PERMISSAO = "Sem permissão para esta ação"
MENSAGEM_AUTH_INDISPONIVEL = "Serviço de autenticação indisponível"


class TokenInvalido(Exception):
    """O token não pode ser aceito. O motivo não é exposto ao cliente."""


class AutenticacaoIndisponivel(Exception):
    """Não foi possível obter as chaves públicas do Supabase."""


class Papel(StrEnum):
    ATENDENTE = "atendente"
    OPERADOR_ESTOQUE = "operador_estoque"
    GERENTE_LOJA = "gerente_loja"
    ADMIN = "admin"


class UsuarioAtual(BaseModel):
    """Usuário do token. `papel` nulo significa cliente; `loja_id` nulo só para admin e cliente."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    email: str | None = None
    papel: Papel | None = None
    loja_id: StrictInt | None = None

    @model_validator(mode="after")
    def _validar_escopo_de_loja(self) -> "UsuarioAtual":
        precisa_de_loja = self.papel is not None and self.papel is not Papel.ADMIN
        if precisa_de_loja != (self.loja_id is not None):
            raise ValueError("papel e loja_id inconsistentes")
        return self


def usuario_de_claims(claims: dict[str, Any]) -> UsuarioAtual:
    if claims.get("role") != AUDIENCIA or claims.get("is_anonymous") is True:
        raise TokenInvalido
    try:
        return UsuarioAtual(
            id=claims["sub"],
            email=claims.get("email") or None,
            papel=claims.get("papel"),
            loja_id=claims.get("loja_id"),
        )
    except (KeyError, ValidationError) as exc:
        raise TokenInvalido from exc
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/Scripts/python -m pytest tests/unit/test_usuario.py -v`
Expected: 20 passed

- [ ] **Step 5: Commit**

```bash
git add app/core/security.py tests/unit/test_usuario.py
git commit -m "feat(auth): usuário autenticado a partir das claims do Supabase" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Validação do JWT com JWKS em cache

**Files:**
- Modify: `app/core/security.py` (acrescentar `CacheJWKS`, `ValidadorToken`)
- Modify: `tests/apoio.py` (chaves, tokens, JWKS simulado, relógio)
- Create: `tests/conftest.py`
- Test: `tests/seguranca/test_validacao_jwt.py`

**Interfaces:**
- Consumes: `usuario_de_claims`, `TokenInvalido`, `AutenticacaoIndisponivel`, constantes da Task 2.
- Produces: `CacheJWKS(url: str, http: httpx.AsyncClient, *, validade: float = 600.0, intervalo_minimo: float = 60.0, relogio: Callable[[], float] = time.monotonic)` com `async carregar() -> None`, `async chave(kid: str) -> jwt.PyJWK`, propriedade `kids -> frozenset[str]`; `ValidadorToken(jwks: CacheJWKS, *, issuer: str)` com `async validar(token: str) -> UsuarioAtual`. Em `tests.apoio`: `ChaveTeste`, `gerar_chave(kid="chave-teste")`, `REMOVER`, `claims_validas(**sobrescrever)`, `assinar(claims, chave)`, `token_sem_assinatura(claims, kid)`, `token_hs256_com_chave_publica(claims, chave)`, `trocar_payload(token, claims)`, `ServidorJWKS`, `RelogioFalso`, `validador_de_teste(servidor, relogio)`. Fixtures: `chave`, `servidor_jwks`, `relogio`, `validador`.

- [ ] **Step 1: Acrescentar utilitários de teste em `tests/apoio.py`**

Acrescentar ao topo os imports e, ao final, o código:
```python
import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from uuid import uuid4

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from jwt.algorithms import ECAlgorithm

from app.core.security import CacheJWKS, ValidadorToken

REMOVER = object()


@dataclass
class ChaveTeste:
    kid: str
    privada: ec.EllipticCurvePrivateKey

    def jwk_publico(self) -> dict[str, str]:
        dados = ECAlgorithm.to_jwk(self.privada.public_key(), as_dict=True)
        dados.update(kid=self.kid, alg="ES256", use="sig")
        return dados


def gerar_chave(kid: str = "chave-teste") -> ChaveTeste:
    return ChaveTeste(kid, ec.generate_private_key(ec.SECP256R1()))


def claims_validas(**sobrescrever: object) -> dict[str, object]:
    agora = int(time.time())
    claims: dict[str, object] = {
        "sub": str(uuid4()),
        "aud": "authenticated",
        "role": "authenticated",
        "iss": ISSUER,
        "iat": agora,
        "exp": agora + 300,
        "email": "pessoa@exemplo.com",
        "session_id": str(uuid4()),
        "is_anonymous": False,
    }
    claims.update(sobrescrever)
    return {nome: valor for nome, valor in claims.items() if valor is not REMOVER}


def assinar(claims: dict[str, object], chave: ChaveTeste) -> str:
    return jwt.encode(claims, chave.privada, algorithm="ES256", headers={"kid": chave.kid})


def _b64(dados: bytes) -> str:
    return base64.urlsafe_b64encode(dados).rstrip(b"=").decode()


def _json_b64(objeto: object) -> str:
    return _b64(json.dumps(objeto, separators=(",", ":")).encode())


def token_sem_assinatura(claims: dict[str, object], kid: str) -> str:
    return f"{_json_b64({'alg': 'none', 'typ': 'JWT', 'kid': kid})}.{_json_b64(claims)}."


def token_hs256_com_chave_publica(claims: dict[str, object], chave: ChaveTeste) -> str:
    """Ataque de confusão de algoritmo: HMAC usando a chave pública (que é pública) como segredo."""
    segredo = chave.privada.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    cabecalho = _json_b64({"alg": "HS256", "typ": "JWT", "kid": chave.kid})
    corpo = _json_b64(claims)
    assinatura = hmac.new(segredo, f"{cabecalho}.{corpo}".encode(), hashlib.sha256).digest()
    return f"{cabecalho}.{corpo}.{_b64(assinatura)}"


def trocar_payload(token: str, claims: dict[str, object]) -> str:
    cabecalho, _, assinatura = token.split(".")
    return f"{cabecalho}.{_json_b64(claims)}.{assinatura}"


@dataclass
class ServidorJWKS:
    """Simula o endpoint de JWKS do Supabase e conta as chamadas recebidas."""

    chaves: list[ChaveTeste]
    chamadas: int = 0
    fora_do_ar: bool = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.chamadas += 1
        if self.fora_do_ar:
            return httpx.Response(503)
        return httpx.Response(200, json={"keys": [c.jwk_publico() for c in self.chaves]})


@dataclass
class RelogioFalso:
    agora: float = field(default=1000.0)

    def __call__(self) -> float:
        return self.agora


def validador_de_teste(servidor: ServidorJWKS, relogio: RelogioFalso) -> ValidadorToken:
    http = httpx.AsyncClient(transport=httpx.MockTransport(servidor))
    return ValidadorToken(CacheJWKS(JWKS_URL, http, relogio=relogio), issuer=ISSUER)
```
(Os imports vão para o topo do arquivo, junto do `from app.core.config import Settings`.)

`tests/conftest.py`:
```python
import pytest

from tests.apoio import RelogioFalso, ServidorJWKS, gerar_chave, validador_de_teste


@pytest.fixture
def chave():
    return gerar_chave()


@pytest.fixture
def servidor_jwks(chave):
    return ServidorJWKS([chave])


@pytest.fixture
def relogio():
    return RelogioFalso()


@pytest.fixture
def validador(servidor_jwks, relogio):
    return validador_de_teste(servidor_jwks, relogio)
```

- [ ] **Step 2: Escrever os testes de segurança (falhando)**

`tests/seguranca/test_validacao_jwt.py`:
```python
import asyncio
import string
import time
from uuid import UUID

import httpx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.security import (
    TAMANHO_MAXIMO_TOKEN,
    AutenticacaoIndisponivel,
    CacheJWKS,
    Papel,
    TokenInvalido,
    ValidadorToken,
)
from tests.apoio import (
    ISSUER,
    JWKS_URL,
    REMOVER,
    RelogioFalso,
    ServidorJWKS,
    assinar,
    claims_validas,
    gerar_chave,
    token_hs256_com_chave_publica,
    token_sem_assinatura,
    trocar_payload,
    validador_de_teste,
)


async def test_token_valido_vira_cliente(validador, chave):
    claims = claims_validas()
    usuario = await validador.validar(assinar(claims, chave))
    assert usuario.id == UUID(claims["sub"])
    assert usuario.email == "pessoa@exemplo.com"
    assert usuario.papel is None


async def test_token_de_gerente_traz_papel_e_loja(validador, chave):
    usuario = await validador.validar(assinar(claims_validas(papel="gerente_loja", loja_id=3), chave))
    assert usuario.papel is Papel.GERENTE_LOJA
    assert usuario.loja_id == 3


@pytest.mark.parametrize(
    "sobrescrever",
    [
        pytest.param({"exp": int(time.time()) - 10}, id="expirado"),
        pytest.param({"aud": "anon", "role": "anon"}, id="token-anon"),
        pytest.param({"aud": REMOVER, "role": "service_role"}, id="token-service-role"),
        pytest.param({"iss": "https://outro.supabase.co/auth/v1"}, id="outro-projeto"),
        pytest.param({"sub": REMOVER}, id="sem-sub"),
        pytest.param({"exp": REMOVER}, id="sem-exp"),
        pytest.param({"iat": REMOVER}, id="sem-iat"),
        pytest.param({"papel": "superadmin", "loja_id": 1}, id="papel-inexistente"),
        pytest.param({"is_anonymous": True}, id="anonimo"),
    ],
)
async def test_claims_invalidas_sao_rejeitadas(validador, chave, sobrescrever):
    with pytest.raises(TokenInvalido):
        await validador.validar(assinar(claims_validas(**sobrescrever), chave))


async def test_alg_none_rejeitado_sem_consultar_jwks(validador, chave, servidor_jwks):
    with pytest.raises(TokenInvalido):
        await validador.validar(token_sem_assinatura(claims_validas(), chave.kid))
    assert servidor_jwks.chamadas == 0


async def test_confusao_hs256_com_chave_publica(validador, chave, servidor_jwks):
    with pytest.raises(TokenInvalido):
        await validador.validar(token_hs256_com_chave_publica(claims_validas(), chave))
    assert servidor_jwks.chamadas == 0


async def test_payload_adulterado_e_rejeitado(validador, chave):
    original = assinar(claims_validas(), chave)
    adulterado = trocar_payload(original, claims_validas(papel="admin"))
    with pytest.raises(TokenInvalido):
        await validador.validar(adulterado)


async def test_assinado_por_outra_chave_com_mesmo_kid(validador, chave):
    impostora = gerar_chave(kid=chave.kid)
    with pytest.raises(TokenInvalido):
        await validador.validar(assinar(claims_validas(), impostora))


async def test_token_gigante_rejeitado_sem_trabalho(validador, chave, servidor_jwks):
    token = assinar(claims_validas(enchimento="x" * TAMANHO_MAXIMO_TOKEN), chave)
    assert len(token) > TAMANHO_MAXIMO_TOKEN
    with pytest.raises(TokenInvalido):
        await validador.validar(token)
    assert servidor_jwks.chamadas == 0


@pytest.mark.parametrize("token", ["", "abc", "a.b.c", "Bearer x", "....", "é.é.é"])
async def test_lixo_e_rejeitado(validador, token):
    with pytest.raises(TokenInvalido):
        await validador.validar(token)


async def test_kid_desconhecido_nao_vira_enxurrada_no_jwks(validador, servidor_jwks, relogio):
    token = assinar(claims_validas(), gerar_chave(kid="kid-desconhecido"))
    for _ in range(50):
        with pytest.raises(TokenInvalido):
            await validador.validar(token)
    assert servidor_jwks.chamadas == 1

    relogio.agora += 61
    with pytest.raises(TokenInvalido):
        await validador.validar(token)
    assert servidor_jwks.chamadas == 2


async def test_chave_rotacionada_vale_depois_da_rebusca_permitida(validador, chave, servidor_jwks, relogio):
    await validador.validar(assinar(claims_validas(), chave))
    nova = gerar_chave(kid="chave-nova")
    servidor_jwks.chaves.append(nova)
    token_novo = assinar(claims_validas(), nova)

    with pytest.raises(TokenInvalido):
        await validador.validar(token_novo)

    relogio.agora += 61
    assert (await validador.validar(token_novo)).id
    assert servidor_jwks.chamadas == 2


async def test_jwks_fora_do_ar_sem_cache_responde_indisponivel(validador, chave, servidor_jwks):
    servidor_jwks.fora_do_ar = True
    token = assinar(claims_validas(), chave)
    for _ in range(2):
        with pytest.raises(AutenticacaoIndisponivel):
            await validador.validar(token)
    assert servidor_jwks.chamadas == 1


async def test_jwks_fora_do_ar_com_cache_vencido_mantem_chaves(validador, chave, servidor_jwks, relogio):
    token = assinar(claims_validas(), chave)
    await validador.validar(token)
    servidor_jwks.fora_do_ar = True
    relogio.agora += 601
    assert (await validador.validar(token)).id
    assert servidor_jwks.chamadas == 2


@pytest.mark.parametrize(
    "resposta",
    [
        pytest.param(lambda: httpx.Response(200, json=[]), id="lista"),
        pytest.param(lambda: httpx.Response(200, json={"keys": []}), id="sem-chaves"),
        pytest.param(lambda: httpx.Response(200, text="nao e json"), id="nao-json"),
        pytest.param(
            lambda: httpx.Response(200, json={"keys": [{"kty": "oct", "k": "c2VncmVkbw", "kid": "h", "alg": "HS256"}]}),
            id="so-hs256",
        ),
        pytest.param(lambda: httpx.Response(500), id="erro-500"),
    ],
)
async def test_jwks_malformado_ou_sem_es256(resposta):
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: resposta()))
    cache = CacheJWKS(JWKS_URL, http)
    with pytest.raises(AutenticacaoIndisponivel):
        await cache.carregar()
    assert cache.kids == frozenset()


async def test_kids_lista_chaves_carregadas(chave):
    http = httpx.AsyncClient(transport=httpx.MockTransport(ServidorJWKS([chave])))
    cache = CacheJWKS(JWKS_URL, http)
    await cache.carregar()
    assert cache.kids == frozenset({chave.kid})


_CHAVE_FUZZ = gerar_chave()
_SEGMENTO = st.text(alphabet=string.ascii_letters + string.digits + "-_", max_size=60)


@settings(max_examples=300, deadline=None)
@given(st.one_of(st.text(max_size=400), st.lists(_SEGMENTO, min_size=3, max_size=3).map(".".join)))
def test_fuzz_validador_so_levanta_token_invalido(token):
    validador = validador_de_teste(ServidorJWKS([_CHAVE_FUZZ]), RelogioFalso())
    with pytest.raises(TokenInvalido):
        asyncio.run(validador.validar(token))


def test_issuer_do_validador_vem_do_supabase_url():
    validador = ValidadorToken(CacheJWKS(JWKS_URL, httpx.AsyncClient()), issuer=ISSUER)
    assert validador.issuer == ISSUER
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `.venv/Scripts/python -m pytest tests/seguranca -v`
Expected: FAIL com `ImportError: cannot import name 'CacheJWKS' from 'app.core.security'`

- [ ] **Step 4: Implementar `CacheJWKS` e `ValidadorToken` em `app/core/security.py`**

Acrescentar aos imports:
```python
import asyncio
import logging
import time
from collections.abc import Callable

import httpx
import jwt
```
e, depois de `usuario_de_claims`:
```python
logger = logging.getLogger(__name__)


def _extrair_chaves(dados: Any) -> dict[str, jwt.PyJWK]:
    if not isinstance(dados, dict):
        raise AutenticacaoIndisponivel("Resposta do JWKS em formato inesperado")
    try:
        conjunto = jwt.PyJWKSet.from_dict(dados)
    except jwt.PyJWTError as exc:
        raise AutenticacaoIndisponivel("JWKS sem chaves utilizáveis") from exc
    chaves = {
        chave.key_id: chave
        for chave in conjunto.keys
        if chave.key_id and chave.algorithm_name == ALGORITMO
    }
    if not chaves:
        raise AutenticacaoIndisponivel("JWKS sem chaves ES256")
    return chaves


class CacheJWKS:
    """Chaves públicas do Supabase em memória.

    Rebusca o JWKS quando o cache vence ou aparece um `kid` desconhecido, mas no máximo
    uma vez por `intervalo_minimo`: tokens forjados não podem virar uma enxurrada de
    requisições contra o Supabase. Se a rebusca falhar, as chaves antigas continuam valendo.
    """

    def __init__(
        self,
        url: str,
        http: httpx.AsyncClient,
        *,
        validade: float = 600.0,
        intervalo_minimo: float = 60.0,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self._url = url
        self._http = http
        self._validade = validade
        self._intervalo_minimo = intervalo_minimo
        self._relogio = relogio
        self._chaves: dict[str, jwt.PyJWK] = {}
        self._carregado_em: float | None = None
        self._ultima_tentativa: float | None = None
        self._trava = asyncio.Lock()

    @property
    def kids(self) -> frozenset[str]:
        return frozenset(self._chaves)

    async def carregar(self) -> None:
        self._ultima_tentativa = self._relogio()
        try:
            resposta = await self._http.get(self._url)
            resposta.raise_for_status()
            dados = resposta.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AutenticacaoIndisponivel("Falha ao buscar o JWKS") from exc
        self._chaves = _extrair_chaves(dados)
        self._carregado_em = self._relogio()

    async def chave(self, kid: str) -> jwt.PyJWK:
        if kid not in self._chaves or self._vencido():
            await self._atualizar()
        if kid in self._chaves:
            return self._chaves[kid]
        if not self._chaves:
            raise AutenticacaoIndisponivel("Nenhuma chave pública disponível")
        raise TokenInvalido

    def _vencido(self) -> bool:
        return self._carregado_em is None or self._relogio() - self._carregado_em >= self._validade

    async def _atualizar(self) -> None:
        async with self._trava:
            agora = self._relogio()
            if self._ultima_tentativa is not None and agora - self._ultima_tentativa < self._intervalo_minimo:
                return
            try:
                await self.carregar()
            except AutenticacaoIndisponivel:
                logger.warning("Não foi possível atualizar o JWKS do Supabase", exc_info=True)


class ValidadorToken:
    """Valida o access token do Supabase, do teste mais barato ao mais caro."""

    def __init__(self, jwks: CacheJWKS, *, issuer: str) -> None:
        self._jwks = jwks
        self.issuer = issuer

    async def validar(self, token: str) -> UsuarioAtual:
        if not token or len(token) > TAMANHO_MAXIMO_TOKEN or not token.isascii():
            raise TokenInvalido
        try:
            cabecalho = jwt.get_unverified_header(token)
        except (jwt.PyJWTError, ValueError) as exc:
            raise TokenInvalido from exc
        kid = cabecalho.get("kid")
        if cabecalho.get("alg") != ALGORITMO or not isinstance(kid, str) or not kid:
            raise TokenInvalido
        chave = await self._jwks.chave(kid)
        try:
            claims = jwt.decode(
                token,
                chave.key,
                algorithms=[ALGORITMO],
                audience=AUDIENCIA,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "sub", "aud", "iss"]},
            )
        except (jwt.PyJWTError, ValueError) as exc:
            raise TokenInvalido from exc
        return usuario_de_claims(claims)
```

- [ ] **Step 5: Rodar e ver passar**

Run: `.venv/Scripts/python -m pytest tests/seguranca tests/unit -v`
Expected: todos passam. Se o fuzz achar uma exceção diferente de `TokenInvalido`, corrija a validação (não o teste) para convertê-la em `TokenInvalido`.

- [ ] **Step 6: Commit**

```bash
git add app/core/security.py tests/apoio.py tests/conftest.py tests/seguranca/test_validacao_jwt.py
git commit -m "feat(auth): validação do JWT do Supabase via JWKS com cache e rebusca limitada" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Dependências `get_current_user` e `requer_papel`

**Files:**
- Modify: `app/core/security.py` (acrescentar dependências FastAPI)
- Test: `tests/api/test_autenticacao.py`

**Interfaces:**
- Consumes: `ValidadorToken.validar`, `TokenInvalido`, `AutenticacaoIndisponivel`, `Papel`, `UsuarioAtual`, mensagens.
- Produces: `esquema_bearer: HTTPBearer`; `get_validador(request) -> ValidadorToken` (lê `request.app.state.validador`); `async get_current_user(...) -> UsuarioAtual`; `requer_papel(*papeis: Papel) -> Callable[..., Awaitable[UsuarioAtual]]`.

- [ ] **Step 1: Escrever os testes (falhando)**

`tests/api/test_autenticacao.py`:
```python
import time
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.core.security import (
    MENSAGEM_AUTH_INDISPONIVEL,
    MENSAGEM_NAO_AUTENTICADO,
    MENSAGEM_SEM_PERMISSAO,
    Papel,
    UsuarioAtual,
    get_current_user,
    requer_papel,
)
from tests.apoio import assinar, claims_validas, gerar_chave


@pytest.fixture
def cliente(validador):
    app = FastAPI()
    app.state.validador = validador

    @app.get("/protegido")
    async def protegido(usuario: Annotated[UsuarioAtual, Depends(get_current_user)]) -> dict[str, str | None]:
        return {"id": str(usuario.id), "papel": usuario.papel}

    @app.get("/gestao")
    async def gestao(
        usuario: Annotated[UsuarioAtual, Depends(requer_papel(Papel.GERENTE_LOJA, Papel.ADMIN))],
    ) -> dict[str, str | None]:
        return {"papel": usuario.papel}

    return TestClient(app)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_token_valido_libera_rota(cliente, chave):
    claims = claims_validas()
    resposta = cliente.get("/protegido", headers=bearer(assinar(claims, chave)))
    assert resposta.status_code == 200
    assert resposta.json() == {"id": claims["sub"], "papel": None}


@pytest.mark.parametrize("cabecalhos", [{}, {"Authorization": "Basic dXN1YXJpbzpzZW5oYQ=="}, {"Authorization": "Bearer "}])
def test_sem_bearer_responde_401(cliente, cabecalhos):
    resposta = cliente.get("/protegido", headers=cabecalhos)
    assert resposta.status_code == 401
    assert resposta.json() == {"detail": MENSAGEM_NAO_AUTENTICADO}
    assert resposta.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "fabricar",
    [
        pytest.param(lambda chave: assinar(claims_validas(exp=int(time.time()) - 5), chave), id="expirado"),
        pytest.param(lambda chave: assinar(claims_validas(aud="anon", role="anon"), chave), id="anon"),
        pytest.param(lambda chave: assinar(claims_validas(), gerar_chave(kid=chave.kid)), id="outra-chave"),
        pytest.param(lambda chave: "lixo", id="lixo"),
    ],
)
def test_erros_de_token_tem_resposta_identica(cliente, chave, fabricar):
    resposta = cliente.get("/protegido", headers=bearer(fabricar(chave)))
    assert resposta.status_code == 401
    assert resposta.json() == {"detail": MENSAGEM_NAO_AUTENTICADO}


def test_jwks_fora_do_ar_responde_503(cliente, chave, servidor_jwks):
    servidor_jwks.fora_do_ar = True
    resposta = cliente.get("/protegido", headers=bearer(assinar(claims_validas(), chave)))
    assert resposta.status_code == 503
    assert resposta.json() == {"detail": MENSAGEM_AUTH_INDISPONIVEL}


@pytest.mark.parametrize(
    ("papel", "loja_id", "status"),
    [
        (None, None, 403),
        ("atendente", 1, 403),
        ("operador_estoque", 1, 403),
        ("gerente_loja", 1, 200),
        ("admin", None, 200),
    ],
)
def test_requer_papel(cliente, chave, papel, loja_id, status):
    extra = {} if papel is None else {"papel": papel, "loja_id": loja_id}
    resposta = cliente.get("/gestao", headers=bearer(assinar(claims_validas(**extra), chave)))
    assert resposta.status_code == status
    if status == 403:
        assert resposta.json() == {"detail": MENSAGEM_SEM_PERMISSAO}


def test_requer_papel_sem_papeis_e_erro_de_programacao():
    with pytest.raises(ValueError):
        requer_papel()


def test_requer_papel_sem_token_responde_401(cliente):
    assert cliente.get("/gestao").status_code == 401


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(valor=st.text(alphabet=st.characters(min_codepoint=32, max_codepoint=126), max_size=300))
def test_fuzz_header_authorization_nunca_passa_de_401(cliente, valor):
    resposta = cliente.get("/protegido", headers={"Authorization": f"Bearer {valor}"})
    assert resposta.status_code == 401
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/Scripts/python -m pytest tests/api/test_autenticacao.py -v`
Expected: FAIL com `ImportError: cannot import name 'get_current_user'`

- [ ] **Step 3: Implementar as dependências em `app/core/security.py`**

Acrescentar aos imports:
```python
from collections.abc import Awaitable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
```
(junte `Awaitable` ao import existente de `collections.abc` e `Annotated` ao de `typing`) e, ao final do arquivo:
```python
esquema_bearer = HTTPBearer(auto_error=False, description="Access token (JWT) emitido pelo Supabase Auth")


def get_validador(request: Request) -> ValidadorToken:
    return request.app.state.validador


def _nao_autenticado() -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        MENSAGEM_NAO_AUTENTICADO,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    credenciais: Annotated[HTTPAuthorizationCredentials | None, Depends(esquema_bearer)],
    validador: Annotated[ValidadorToken, Depends(get_validador)],
) -> UsuarioAtual:
    if credenciais is None:
        raise _nao_autenticado()
    try:
        return await validador.validar(credenciais.credentials)
    except TokenInvalido:
        raise _nao_autenticado() from None
    except AutenticacaoIndisponivel:
        logger.error("JWKS do Supabase indisponível ao validar token")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, MENSAGEM_AUTH_INDISPONIVEL) from None


def requer_papel(*papeis: Papel) -> Callable[..., Awaitable[UsuarioAtual]]:
    if not papeis:
        raise ValueError("requer_papel precisa de ao menos um papel")
    permitidos = frozenset(papeis)

    async def verificar_papel(usuario: Annotated[UsuarioAtual, Depends(get_current_user)]) -> UsuarioAtual:
        if usuario.papel not in permitidos:
            raise HTTPException(status.HTTP_403_FORBIDDEN, MENSAGEM_SEM_PERMISSAO)
        return usuario

    return verificar_papel
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/Scripts/python -m pytest tests -v`
Expected: todos passam.

- [ ] **Step 5: Commit**

```bash
git add app/core/security.py tests/api/test_autenticacao.py
git commit -m "feat(auth): dependências get_current_user e requer_papel" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Pool asyncpg, transação e `/health`

**Files:**
- Create: `app/core/db.py`
- Modify: `tests/apoio.py` (pool e conexão falsos)
- Test: `tests/unit/test_db.py`

**Interfaces:**
- Consumes: `Settings.database_url`, `Settings.db_pool_max`.
- Produces: `async criar_pool(settings) -> asyncpg.Pool`; `get_pool(request) -> asyncpg.Pool` (lê `request.app.state.pool`); `get_conexao` (dependência com yield); `get_transacao` (dependência com yield, commit/rollback); `router_saude` com `GET /health`; `MENSAGEM_BANCO_INDISPONIVEL`. Em `tests.apoio`: `ConexaoFalsa(falhar=False)` com `eventos: list[str]`, `PoolFalso(conexao, falha_aquisicao=None)` com `liberadas: int`, `fechado: bool`.

- [ ] **Step 1: Acrescentar fakes em `tests/apoio.py`**

```python
class TransacaoFalsa:
    def __init__(self, eventos: list[str]) -> None:
        self._eventos = eventos

    async def __aenter__(self) -> None:
        self._eventos.append("begin")

    async def __aexit__(self, tipo: object, exc: object, tb: object) -> bool:
        self._eventos.append("rollback" if tipo else "commit")
        return False


class ConexaoFalsa:
    def __init__(self, falhar: bool = False) -> None:
        self.falhar = falhar
        self.eventos: list[str] = []

    async def fetchval(self, consulta: str, *args: object, timeout: float | None = None) -> int:
        if self.falhar:
            raise OSError("conexão perdida")
        return 1

    def transaction(self) -> TransacaoFalsa:
        return TransacaoFalsa(self.eventos)


class PoolFalso:
    def __init__(self, conexao: ConexaoFalsa, falha_aquisicao: Exception | None = None) -> None:
        self.conexao = conexao
        self.falha_aquisicao = falha_aquisicao
        self.liberadas = 0
        self.fechado = False

    async def acquire(self, timeout: float | None = None) -> ConexaoFalsa:
        if self.falha_aquisicao is not None:
            raise self.falha_aquisicao
        return self.conexao

    async def release(self, conexao: ConexaoFalsa) -> None:
        self.liberadas += 1

    async def close(self) -> None:
        self.fechado = True
```

- [ ] **Step 2: Escrever os testes (falhando)**

`tests/unit/test_db.py`:
```python
from typing import Annotated

import asyncpg
import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core.db import MENSAGEM_BANCO_INDISPONIVEL, criar_pool, get_transacao, router_saude
from tests.apoio import DATABASE_URL_TESTE, ConexaoFalsa, PoolFalso, settings_de_teste


def montar(pool: PoolFalso) -> TestClient:
    app = FastAPI()
    app.state.pool = pool
    app.include_router(router_saude)

    @app.post("/ok")
    async def ok(conexao: Annotated[ConexaoFalsa, Depends(get_transacao)]) -> dict[str, bool]:
        return {"ok": True}

    @app.post("/conflito")
    async def conflito(conexao: Annotated[ConexaoFalsa, Depends(get_transacao)]) -> None:
        raise HTTPException(409, "Estado não permite a ação")

    return TestClient(app)


def test_health_ok_e_devolve_conexao():
    pool = PoolFalso(ConexaoFalsa())
    resposta = montar(pool).get("/health")
    assert resposta.status_code == 200
    assert resposta.json() == {"status": "ok"}
    assert pool.liberadas == 1


@pytest.mark.parametrize("falha", [TimeoutError(), OSError("recusada"), asyncpg.InterfaceError("pool fechando")])
def test_health_503_quando_nao_obtem_conexao(falha):
    resposta = montar(PoolFalso(ConexaoFalsa(), falha_aquisicao=falha)).get("/health")
    assert resposta.status_code == 503
    assert resposta.json() == {"detail": MENSAGEM_BANCO_INDISPONIVEL}


def test_health_503_quando_consulta_falha_e_conexao_volta_ao_pool():
    pool = PoolFalso(ConexaoFalsa(falhar=True))
    resposta = montar(pool).get("/health")
    assert resposta.status_code == 503
    assert pool.liberadas == 1


def test_transacao_faz_commit_quando_a_rota_termina_bem():
    pool = PoolFalso(ConexaoFalsa())
    assert montar(pool).post("/ok").status_code == 200
    assert pool.conexao.eventos == ["begin", "commit"]
    assert pool.liberadas == 1


def test_transacao_faz_rollback_quando_a_rota_levanta_erro():
    pool = PoolFalso(ConexaoFalsa())
    resposta = montar(pool).post("/conflito")
    assert resposta.status_code == 409
    assert pool.conexao.eventos == ["begin", "rollback"]
    assert pool.liberadas == 1


async def test_criar_pool_usa_pooler_sem_cache_de_statements(monkeypatch):
    capturado: dict[str, object] = {}

    async def create_pool_falso(**kwargs: object) -> str:
        capturado.update(kwargs)
        return "pool"

    monkeypatch.setattr(asyncpg, "create_pool", create_pool_falso)
    assert await criar_pool(settings_de_teste()) == "pool"
    assert capturado["dsn"] == DATABASE_URL_TESTE
    assert capturado["statement_cache_size"] == 0
    assert capturado["ssl"] == "require"
    assert capturado["max_size"] == 5
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `.venv/Scripts/python -m pytest tests/unit/test_db.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.core.db'`

- [ ] **Step 4: Implementar `app/core/db.py`**

```python
"""Pool asyncpg com o Postgres do Supabase (pooler em modo transação).

Esta conexão ignora RLS de propósito (CLAUDE.md, seção 2): toda checagem de papel e
de escopo de loja fica no código Python. Queries sempre com $1, $2.
"""

import logging
from collections.abc import AsyncIterator
from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.config import Settings

logger = logging.getLogger(__name__)

TEMPO_LIMITE_AQUISICAO = 5.0
TEMPO_LIMITE_COMANDO = 10.0
MENSAGEM_BANCO_INDISPONIVEL = "Banco de dados indisponível"
_ERROS_DE_CONEXAO = (TimeoutError, OSError, asyncpg.PostgresError, asyncpg.InterfaceError)


async def criar_pool(settings: Settings) -> asyncpg.Pool:
    # statement_cache_size=0: o pooler em modo transação não preserva prepared statements.
    return await asyncpg.create_pool(
        dsn=settings.database_url.get_secret_value(),
        min_size=1,
        max_size=settings.db_pool_max,
        statement_cache_size=0,
        command_timeout=TEMPO_LIMITE_COMANDO,
        timeout=TEMPO_LIMITE_AQUISICAO,
        ssl="require",
    )


def get_pool(request: Request) -> asyncpg.Pool:
    return request.app.state.pool


def _banco_indisponivel() -> HTTPException:
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, MENSAGEM_BANCO_INDISPONIVEL)


async def get_conexao(
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> AsyncIterator[asyncpg.Connection]:
    try:
        conexao = await pool.acquire(timeout=TEMPO_LIMITE_AQUISICAO)
    except _ERROS_DE_CONEXAO as exc:
        logger.error("Falha ao obter conexão do pool: %s", type(exc).__name__)
        raise _banco_indisponivel() from None
    try:
        yield conexao
    finally:
        await pool.release(conexao)


async def get_transacao(
    conexao: Annotated[asyncpg.Connection, Depends(get_conexao)],
) -> AsyncIterator[asyncpg.Connection]:
    """Conexão dentro de uma transação: commit se a rota terminar bem, rollback se levantar exceção."""
    async with conexao.transaction():
        yield conexao


router_saude = APIRouter(tags=["saude"])


@router_saude.get("/health")
async def health(conexao: Annotated[asyncpg.Connection, Depends(get_conexao)]) -> dict[str, str]:
    try:
        await conexao.fetchval("select 1", timeout=2)
    except _ERROS_DE_CONEXAO:
        raise _banco_indisponivel() from None
    return {"status": "ok"}
```

- [ ] **Step 5: Rodar e ver passar**

Run: `.venv/Scripts/python -m pytest tests -v`
Expected: todos passam. Se `test_transacao_faz_rollback...` mostrar `["begin", "commit"]`, a versão do FastAPI não repassa a exceção da rota para a dependência: pare e reporte, porque o helper de transação não seria confiável.

- [ ] **Step 6: Commit**

```bash
git add app/core/db.py tests/apoio.py tests/unit/test_db.py
git commit -m "feat(db): pool asyncpg do pooler, transação por requisição e /health" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Limite de requisições

**Files:**
- Create: `app/core/limite_requisicoes.py`
- Test: `tests/unit/test_limite_requisicoes.py`

**Interfaces:**
- Consumes: `Settings.limite_padrao`, `Settings.limite_armazenamento`, `get_current_user`, `UsuarioAtual`, `TokenInvalido`.
- Produces: `MENSAGEM_LIMITE`; `chave_por_ip(request) -> str`; `configurar_limites(app, settings) -> Limiter` (registra `app.state.limiter`, handler de 429 e `SlowAPIMiddleware`); `limite_por_usuario(limite: str, *, escopo: str) -> Callable[..., Awaitable[UsuarioAtual]]`.

Contexto: no slowapi, rotas com decorator pulam o middleware (inclusive `application_limits`), e o decorator roda depois das dependências; uma inundação de tokens inválidos numa rota decorada nunca seria contada. Por isso não usamos o decorator: o limite global por IP fica no middleware (vale para todas as rotas, antes da autenticação) e o limite por usuário é uma dependência que reusa o armazenamento do slowapi.

- [ ] **Step 1: Escrever os testes (falhando)**

`tests/unit/test_limite_requisicoes.py`:
```python
from types import SimpleNamespace
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header
from fastapi.testclient import TestClient

from app.core.limite_requisicoes import (
    MENSAGEM_LIMITE,
    chave_por_ip,
    configurar_limites,
    limite_por_usuario,
)
from app.core.security import TokenInvalido, UsuarioAtual, get_current_user
from tests.apoio import settings_de_teste


class ValidadorQueRecusa:
    async def validar(self, token: str) -> UsuarioAtual:
        raise TokenInvalido


def usuario_pelo_header(x_usuario: Annotated[str, Header()]) -> UsuarioAtual:
    return UsuarioAtual(id=UUID(x_usuario))


def montar(limite_padrao: str, *, usuario_de_teste: bool = False) -> FastAPI:
    app = FastAPI()
    configurar_limites(app, settings_de_teste(limite_padrao=limite_padrao))
    app.state.validador = ValidadorQueRecusa()

    @app.get("/a")
    async def rota_a() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/b")
    async def rota_b() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/protegido")
    async def protegido(usuario: Annotated[UsuarioAtual, Depends(get_current_user)]) -> dict[str, str]:
        return {"id": str(usuario.id)}

    @app.get("/limitado")
    async def limitado(
        usuario: Annotated[UsuarioAtual, Depends(limite_por_usuario("2/minute", escopo="teste"))],
    ) -> dict[str, str]:
        return {"id": str(usuario.id)}

    if usuario_de_teste:
        app.dependency_overrides[get_current_user] = usuario_pelo_header
    return app


def cliente(app: FastAPI, ip: str = "10.0.0.1") -> TestClient:
    return TestClient(app, client=(ip, 50000))


def assert_429(resposta) -> None:
    assert resposta.status_code == 429
    assert resposta.json() == {"detail": MENSAGEM_LIMITE}
    assert 1 <= int(resposta.headers["Retry-After"]) <= 60


def test_limite_global_por_ip():
    c = cliente(montar("3/minute"))
    assert [c.get("/a").status_code for _ in range(3)] == [200, 200, 200]
    assert_429(c.get("/a"))


def test_limite_global_e_compartilhado_entre_rotas():
    c = cliente(montar("3/minute"))
    assert [c.get("/a").status_code, c.get("/b").status_code, c.get("/a").status_code] == [200, 200, 200]
    assert_429(c.get("/b"))


def test_ips_diferentes_tem_cotas_separadas():
    app = montar("1/minute")
    assert cliente(app, "10.0.0.1").get("/a").status_code == 200
    assert cliente(app, "10.0.0.2").get("/a").status_code == 200
    assert_429(cliente(app, "10.0.0.1").get("/a"))


def test_x_forwarded_for_forjado_nao_troca_a_chave():
    c = cliente(montar("2/minute"))
    assert c.get("/a", headers={"X-Forwarded-For": "1.1.1.1"}).status_code == 200
    assert c.get("/a", headers={"X-Forwarded-For": "2.2.2.2"}).status_code == 200
    assert_429(c.get("/a", headers={"X-Forwarded-For": "3.3.3.3"}))


def test_enxurrada_de_tokens_invalidos_e_barrada_por_ip():
    c = cliente(montar("3/minute"))
    respostas = [c.get("/protegido", headers={"Authorization": "Bearer forjado"}) for _ in range(3)]
    assert [r.status_code for r in respostas] == [401, 401, 401]
    assert_429(c.get("/protegido", headers={"Authorization": "Bearer forjado"}))


def test_limite_por_usuario_isola_cotas():
    c = cliente(montar("1000/minute", usuario_de_teste=True))
    ana, bruno = str(uuid4()), str(uuid4())
    assert [c.get("/limitado", headers={"X-Usuario": ana}).status_code for _ in range(2)] == [200, 200]
    assert_429(c.get("/limitado", headers={"X-Usuario": ana}))
    assert c.get("/limitado", headers={"X-Usuario": bruno}).status_code == 200


def test_chave_por_ip_sem_cliente():
    assert chave_por_ip(SimpleNamespace(client=None)) == "desconhecido"
    assert chave_por_ip(SimpleNamespace(client=SimpleNamespace(host="10.0.0.9"))) == "10.0.0.9"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/Scripts/python -m pytest tests/unit/test_limite_requisicoes.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.core.limite_requisicoes'`

- [ ] **Step 3: Implementar `app/core/limite_requisicoes.py`**

```python
"""Limites de requisições.

- Global por IP, no middleware: vale para todas as rotas e roda antes da autenticação,
  então uma enxurrada de tokens inválidos também é barrada.
- Por usuário, como dependência: chave = id do usuário já validado (nunca um `sub` não verificado).

Login, cadastro e refresh são limitados pelo próprio Supabase Auth.
O armazenamento padrão é em memória (um processo); com vários processos, use Redis
em LIMITE_ARMAZENAMENTO.
"""

import math
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from limits import RateLimitItem, parse
from limits.strategies import RateLimiter
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.config import Settings
from app.core.security import UsuarioAtual, get_current_user

MENSAGEM_LIMITE = "Muitas requisições. Tente novamente em instantes."


def chave_por_ip(request: Request) -> str:
    """IP do socket. Atrás de proxy, quem traduz X-Forwarded-For é o servidor
    (uvicorn --proxy-headers com --forwarded-allow-ips restrito), nunca a aplicação."""
    return request.client.host if request.client else "desconhecido"


def _segundos_ate_liberar(estrategia: RateLimiter, limite: RateLimitItem, chaves: Sequence[str]) -> int:
    reinicio = estrategia.get_window_stats(limite, *chaves).reset_time
    return max(1, math.ceil(reinicio - time.time()))


def _tratar_limite_excedido(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    limite, chaves = request.state.view_rate_limit
    segundos = _segundos_ate_liberar(request.app.state.limiter.limiter, limite, chaves)
    return JSONResponse(
        {"detail": MENSAGEM_LIMITE},
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        headers={"Retry-After": str(segundos)},
    )


def configurar_limites(app: FastAPI, settings: Settings) -> Limiter:
    limiter = Limiter(
        key_func=chave_por_ip,
        application_limits=[settings.limite_padrao],
        storage_uri=settings.limite_armazenamento,
        strategy="moving-window",
    )
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _tratar_limite_excedido)
    app.add_middleware(SlowAPIMiddleware)
    return limiter


def limite_por_usuario(limite: str, *, escopo: str) -> Callable[..., Awaitable[UsuarioAtual]]:
    item = parse(limite)

    async def verificar_limite(
        request: Request,
        usuario: Annotated[UsuarioAtual, Depends(get_current_user)],
    ) -> UsuarioAtual:
        estrategia = request.app.state.limiter.limiter
        chaves = ("usuario", str(usuario.id), escopo)
        if not estrategia.hit(item, *chaves):
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                MENSAGEM_LIMITE,
                headers={"Retry-After": str(_segundos_ate_liberar(estrategia, item, chaves))},
            )
        return usuario

    return verificar_limite
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/Scripts/python -m pytest tests -v`
Expected: todos passam.

- [ ] **Step 5: Commit**

```bash
git add app/core/limite_requisicoes.py tests/unit/test_limite_requisicoes.py
git commit -m "feat(seguranca): limite de requisições global por IP e por usuário" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: App FastAPI (lifespan, CORS, OpenAPI) e guarda de campos de permissão

**Files:**
- Create: `app/main.py`
- Test: `tests/api/test_app.py`, `tests/api/test_guarda_campos_permissao.py`

**Interfaces:**
- Consumes: `Settings`, `get_settings`, `criar_pool`, `router_saude`, `configurar_limites`, `CacheJWKS`, `ValidadorToken`, `AutenticacaoIndisponivel`, `get_current_user`.
- Produces: `criar_app(settings: Settings | None = None) -> FastAPI`. Execução: `uvicorn app.main:criar_app --factory`.

- [ ] **Step 1: Escrever os testes (falhando)**

`tests/api/test_app.py`:
```python
import logging
from typing import Annotated

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from app.core.security import AutenticacaoIndisponivel, CacheJWKS, UsuarioAtual, ValidadorToken, get_current_user
from app.main import criar_app
from tests.apoio import ConexaoFalsa, PoolFalso, settings_de_teste

ORIGEM_FRONT = "http://localhost:5173"


def montar(validador, **sobrescrever):
    app = criar_app(settings_de_teste(**sobrescrever))
    app.state.validador = validador
    app.state.pool = PoolFalso(ConexaoFalsa())
    return app


@pytest.fixture
def cliente(validador):
    return TestClient(montar(validador))


def test_health(cliente):
    assert cliente.get("/health").json() == {"status": "ok"}


def test_cors_libera_origem_configurada(cliente):
    resposta = cliente.options(
        "/health",
        headers={
            "Origin": ORIGEM_FRONT,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert resposta.status_code == 200
    assert resposta.headers["access-control-allow-origin"] == ORIGEM_FRONT


def test_cors_nega_origem_desconhecida(cliente):
    resposta = cliente.options(
        "/health",
        headers={"Origin": "https://site-malicioso.example", "Access-Control-Request-Method": "GET"},
    )
    assert resposta.status_code == 400
    assert "access-control-allow-origin" not in resposta.headers


def test_resposta_429_leva_headers_de_cors(validador):
    cliente = TestClient(montar(validador, limite_padrao="1/minute"))
    assert cliente.get("/health", headers={"Origin": ORIGEM_FRONT}).status_code == 200
    resposta = cliente.get("/health", headers={"Origin": ORIGEM_FRONT})
    assert resposta.status_code == 429
    assert resposta.headers["access-control-allow-origin"] == ORIGEM_FRONT


def test_openapi_declara_bearer_nas_rotas_protegidas(validador):
    app = montar(validador)

    @app.get("/rota-protegida-de-teste")
    async def rota(usuario: Annotated[UsuarioAtual, Depends(get_current_user)]) -> dict[str, str]:
        return {"id": str(usuario.id)}

    esquema = TestClient(app).get("/openapi.json").json()
    bearer = esquema["components"]["securitySchemes"]["HTTPBearer"]
    assert (bearer["type"], bearer["scheme"]) == ("http", "bearer")
    assert esquema["paths"]["/rota-protegida-de-teste"]["get"]["security"] == [{"HTTPBearer": []}]


def test_lifespan_tolera_jwks_fora_e_fecha_o_pool(monkeypatch, caplog):
    pool = PoolFalso(ConexaoFalsa())

    async def criar_pool_falso(settings):
        return pool

    async def carregar_com_falha(self):
        raise AutenticacaoIndisponivel("fora do ar")

    monkeypatch.setattr("app.main.criar_pool", criar_pool_falso)
    monkeypatch.setattr(CacheJWKS, "carregar", carregar_com_falha)
    app = criar_app(settings_de_teste())

    with caplog.at_level(logging.WARNING), TestClient(app) as cliente:
        assert cliente.get("/health").status_code == 200
        assert isinstance(app.state.validador, ValidadorToken)
        assert app.state.validador.issuer == "https://ref-teste.supabase.co/auth/v1"

    assert pool.fechado
    assert "JWKS indisponível no startup" in caplog.text
```

`tests/api/test_guarda_campos_permissao.py`:
```python
"""CLAUDE.md, seção 3: papel, loja e cliente vêm do token ou de um fluxo admin, nunca do input."""

from typing import get_args

from fastapi import FastAPI
from fastapi.dependencies.utils import get_flat_dependant
from fastapi.routing import APIRoute
from pydantic import BaseModel

from app.main import criar_app
from tests.apoio import settings_de_teste

CAMPOS_PROIBIDOS = {"papel", "id_loja", "loja_id", "id_cliente"}
# Fluxos admin que podem receber esses campos entram aqui, um a um, de forma explícita.
# Ex.: ("PATCH", "/usuarios/{id}/papel").
ROTAS_LIBERADAS: set[tuple[str, str]] = set()


def _nomes_em(tipo: object, vistos: set[type]) -> set[str]:
    nomes: set[str] = set()
    if isinstance(tipo, type) and issubclass(tipo, BaseModel) and tipo not in vistos:
        vistos.add(tipo)
        for nome, campo in tipo.model_fields.items():
            nomes |= {nome, campo.alias or nome}
            nomes |= _nomes_em(campo.annotation, vistos)
    for argumento in get_args(tipo):
        nomes |= _nomes_em(argumento, vistos)
    return nomes


def _campos_de_entrada(rota: APIRoute) -> set[str]:
    dependente = get_flat_dependant(rota.dependant)
    parametros = [
        *dependente.body_params,
        *dependente.query_params,
        *dependente.header_params,
        *dependente.cookie_params,
    ]
    nomes: set[str] = set()
    for parametro in parametros:
        nomes |= {parametro.name, parametro.alias}
        nomes |= _nomes_em(parametro.field_info.annotation, set())
    return nomes


def violacoes(app: FastAPI) -> list[str]:
    encontradas = []
    for rota in app.routes:
        if not isinstance(rota, APIRoute):
            continue
        for metodo in sorted(rota.methods):
            if (metodo, rota.path) in ROTAS_LIBERADAS:
                continue
            proibidos = _campos_de_entrada(rota) & CAMPOS_PROIBIDOS
            if proibidos:
                encontradas.append(f"{metodo} {rota.path}: {sorted(proibidos)}")
    return encontradas


def test_nenhuma_rota_aceita_campos_de_permissao():
    assert violacoes(criar_app(settings_de_teste())) == []


class Endereco(BaseModel):
    cep: str
    id_cliente: int


class PedidoEntrada(BaseModel):
    itens: list[int]
    entrega: Endereco


class UsuarioEntrada(BaseModel):
    nome: str
    papel: str


def test_guarda_detecta_campos_proibidos():
    app = FastAPI()

    @app.post("/direto")
    async def direto(corpo: UsuarioEntrada) -> None: ...

    @app.post("/aninhado")
    async def aninhado(corpo: PedidoEntrada) -> None: ...

    @app.get("/consulta")
    async def consulta(id_loja: int) -> None: ...

    assert violacoes(app) == [
        "POST /direto: ['papel']",
        "POST /aninhado: ['id_cliente']",
        "GET /consulta: ['id_loja']",
    ]
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/Scripts/python -m pytest tests/api -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 3: Implementar `app/main.py`**

```python
"""API da Casa Lorenzi. Execução: uvicorn app.main:criar_app --factory"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import Settings, get_settings
from app.core.db import criar_pool, router_saude
from app.core.limite_requisicoes import configurar_limites
from app.core.security import AutenticacaoIndisponivel, CacheJWKS, ValidadorToken

logger = logging.getLogger(__name__)


def criar_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with httpx.AsyncClient(timeout=5.0) as http:
            jwks = CacheJWKS(settings.supabase_jwks_url, http)
            try:
                await jwks.carregar()
            except AutenticacaoIndisponivel:
                logger.warning("JWKS indisponível no startup; nova tentativa em até 1 minuto")
            app.state.validador = ValidadorToken(jwks, issuer=settings.supabase_issuer)
            app.state.pool = await criar_pool(settings)
            try:
                yield
            finally:
                await app.state.pool.close()

    app = FastAPI(title="Casa Lorenzi API", version="0.1.0", lifespan=lifespan)
    configurar_limites(app, settings)
    # CORS por último para ficar por fora: respostas 401 e 429 também levam os headers.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        max_age=600,
    )
    app.include_router(router_saude)
    return app
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/Scripts/python -m pytest tests -v`
Expected: todos passam.

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/api/test_app.py tests/api/test_guarda_campos_permissao.py
git commit -m "feat(api): app FastAPI com lifespan, CORS e guarda de campos de permissão" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Testes live, README e verificação final

**Files:**
- Create: `tests/live/test_supabase_real.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `Settings`, `criar_pool`, `CacheJWKS`, `ValidadorToken`, `criar_app`.

- [ ] **Step 1: Escrever os testes live**

`tests/live/test_supabase_real.py`:
```python
"""Testes contra o Supabase real, somente leitura. Rode com: pytest -m live

Exigem o .env no formato do .env.example. O teste de login também exige
SUPABASE_PUBLISHABLE_KEY, TEST_USER_EMAIL e TEST_USER_PASSWORD (usuário de teste
criado no dashboard do Supabase).
"""

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import Settings
from app.core.db import criar_pool
from app.core.security import CacheJWKS, ValidadorToken
from app.main import criar_app

pytestmark = pytest.mark.live


class CredenciaisDeTeste(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    supabase_publishable_key: str = ""
    test_user_email: str = ""
    test_user_password: str = ""


@pytest.fixture(scope="module")
def settings() -> Settings:
    return Settings()


@pytest.fixture(scope="module")
def credenciais() -> CredenciaisDeTeste:
    dados = CredenciaisDeTeste()
    if not (dados.supabase_publishable_key and dados.test_user_email and dados.test_user_password):
        pytest.skip("Defina SUPABASE_PUBLISHABLE_KEY, TEST_USER_EMAIL e TEST_USER_PASSWORD no .env")
    return dados


async def test_pool_conecta_no_pooler_em_modo_transacao(settings):
    pool = await criar_pool(settings)
    try:
        async with pool.acquire() as conexao:
            for numero in range(3):
                async with conexao.transaction():
                    assert await conexao.fetchval("select $1::int", numero) == numero
            assert await conexao.fetchval(
                "select rolbypassrls from pg_roles where rolname = current_user"
            ) is True
    finally:
        await pool.close()


async def test_jwks_real_tem_chave_es256(settings):
    async with httpx.AsyncClient(timeout=5.0) as http:
        cache = CacheJWKS(settings.supabase_jwks_url, http)
        await cache.carregar()
        assert cache.kids


def test_app_real_sobe_e_responde_health(settings):
    with TestClient(criar_app(settings)) as cliente:
        assert cliente.get("/health").json() == {"status": "ok"}


async def test_login_refresh_e_logout_do_supabase(settings, credenciais):
    async with (
        httpx.AsyncClient(
            base_url=settings.supabase_issuer,
            headers={"apikey": credenciais.supabase_publishable_key},
            timeout=10.0,
        ) as auth,
        httpx.AsyncClient(timeout=5.0) as http,
    ):
        validador = ValidadorToken(CacheJWKS(settings.supabase_jwks_url, http), issuer=settings.supabase_issuer)

        login = await auth.post(
            "/token",
            params={"grant_type": "password"},
            json={"email": credenciais.test_user_email, "password": credenciais.test_user_password},
        )
        assert login.status_code == 200, login.text
        sessao = login.json()
        usuario = await validador.validar(sessao["access_token"])
        assert usuario.email == credenciais.test_user_email.lower()

        renovada = await auth.post(
            "/token", params={"grant_type": "refresh_token"}, json={"refresh_token": sessao["refresh_token"]}
        )
        assert renovada.status_code == 200, renovada.text
        nova = renovada.json()
        assert (await validador.validar(nova["access_token"])).id == usuario.id

        saida = await auth.post("/logout", headers={"Authorization": f"Bearer {nova['access_token']}"})
        assert saida.status_code == 204
        reuso = await auth.post(
            "/token", params={"grant_type": "refresh_token"}, json={"refresh_token": nova["refresh_token"]}
        )
        assert reuso.status_code in (400, 401)

        # Validação sem estado: o access token segue válido até o exp (CLAUDE.md, seção 3).
        assert (await validador.validar(nova["access_token"])).id == usuario.id
```

- [ ] **Step 2: Confirmar que os testes live ficam fora da execução padrão**

Run: `.venv/Scripts/python -m pytest tests -q`
Expected: todos passam e os 4 testes live aparecem como `deselected`.

- [ ] **Step 3: Rodar os testes live (somente se o `.env` já estiver no formato do `.env.example`)**

Run: `.venv/Scripts/python -m pytest -m live -v`
Expected: 3 passam; o de login passa ou é pulado se as credenciais de teste não existirem. Se o `.env` ainda estiver no formato antigo, não rode e registre como pendência.

- [ ] **Step 4: Atualizar `README.md`**

```markdown
# Backend_CasaLorenzi
Repositorio do backend para casa lorenzi

## Rodando localmente

1. Python 3.12 e a venv: `python -m venv .venv` e `.venv/Scripts/python -m pip install -r requirements-dev.txt`
2. Copie `.env.example` para `.env` e preencha (pooler do Supabase em modo transação, porta 6543).
3. Suba a API: `.venv/Scripts/python -m uvicorn app.main:criar_app --factory --reload`
4. Documentação: http://localhost:8000/docs (botão Authorize recebe o access token do Supabase).

## Autenticação

Login, cadastro, refresh e logout são feitos pelo front com `supabase-js`. O backend só valida
o access token (ES256 via JWKS do projeto) e expõe `get_current_user` e `requer_papel` em
`app/core/security.py`. O papel e a loja chegam no token pelo Custom Access Token Hook.

## Testes

- Padrão (sem rede): `.venv/Scripts/python -m pytest`
- Cobertura: `.venv/Scripts/python -m pytest --cov --cov-report=term-missing --cov-fail-under=90`
- Contra o Supabase real (somente leitura): `.venv/Scripts/python -m pytest -m live`
- Qualidade: `.venv/Scripts/python -m ruff check .`, `.venv/Scripts/python -m bandit -r app`, `.venv/Scripts/python -m pip_audit -r requirements.txt`

## Deploy (Render)

`uvicorn app.main:criar_app --factory --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips=<ips do proxy>`.
O limite por IP usa o IP que o uvicorn entrega; valide no Render qual configuração de
proxy evita `X-Forwarded-For` forjado antes de abrir para o público.
```

- [ ] **Step 5: Verificação final**

Run, em sequência:
```bash
.venv/Scripts/python -m pytest --cov --cov-report=term-missing --cov-fail-under=90
.venv/Scripts/python -m ruff check .
.venv/Scripts/python -m bandit -q -r app
.venv/Scripts/python -m pip_audit -r requirements.txt
```
Expected: testes passam com cobertura ≥ 90%; ruff sem erros; bandit sem achados de severidade média/alta; pip-audit sem vulnerabilidades conhecidas. Corrija o que aparecer antes de commitar.

- [ ] **Step 6: Commit**

```bash
git add tests/live/test_supabase_real.py README.md
git commit -m "test(live): testes contra o Supabase real e instruções de uso" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
