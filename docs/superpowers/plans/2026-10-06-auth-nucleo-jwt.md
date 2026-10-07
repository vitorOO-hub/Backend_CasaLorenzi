# Núcleo de auth (JWT do Supabase + trava por flag) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validar o JWT do Supabase (ES256, JWKS) e oferecer `get_current_user`, `requer_papel` e escopo de loja ao código Python, com uma trava por flag (`AUTENTICACAO_OBRIGATORIA`, padrão desligada) ligada em `app/api/router.py`.

**Architecture:** Arquivos novos em `app/core/` (`papeis.py`, `erros_auth.py`, `jwks.py`, `security.py`). O cache de chaves públicas (`ProvedorChaves`) é injetável para os testes. A trava entra só em `app/api/router.py`, via `include_router(..., dependencies=[...])`, e com a flag desligada não bloqueia nada, para a tela do cliente do outro integrante continuar funcionando. Nenhum módulo de negócio é editado.

**Tech Stack:** FastAPI (rotas e dependências síncronas), PyJWT + cryptography (ES256), httpx (busca do JWKS), pydantic v2, pytest.

**Spec:** `docs/superpowers/specs/2026-10-06-auth-rls-sobre-intermediaria-design.md` (seções "Decisões" e "1. Núcleo de auth"; a seção "2. Banco" é o Plano 2, separado). Este plano substitui, nesta branch, o plano `2026-10-05-supabase-auth-nucleo.md`, que assumia acesso assíncrono.

## Global Constraints

- Branch de trabalho: `feat/rls-policies-auth` (a partir de `origin/intermediaria`). **Não editar** arquivos de módulo do outro integrante: `app/admin/`, `app/atendimento/`, `app/compras/`, `app/estoque/`, `app/movimentacoes/` e seus testes.
- Arquivos existentes que este plano pode alterar: `app/api/router.py`, `app/core/config.py`, `.env.example`, `README.md` e o spec. Tudo o mais é arquivo novo.
- Comandos assumem a raiz do repositório e o interpretador do projeto: `.venv/Scripts/python.exe` (abaixo, `PY`). Shell: Git Bash.
- Idioma do domínio: nomes, mensagens de erro e comentários em português, sem acentos em identificadores.
- Algoritmo do JWT: **somente ES256**, chaves via JWKS em `<SUPABASE_URL>/auth/v1/.well-known/jwks.json` (verificado no projeto real: chave `EC`, `P-256`, `ES256`). Rejeitar qualquer outro `alg`, inclusive `none` e `HS256`.
- Validações obrigatórias do token: assinatura, `exp`, `aud="authenticated"`, `iss="<SUPABASE_URL>/auth/v1"`, `sub`; tamanho máximo 8192 caracteres; `role == "authenticated"`; recusar `is_anonymous == true`.
- Papéis: `atendente`, `operador_estoque`, `gerente_loja`, `admin`. `atendente`, `operador_estoque` e `gerente_loja` exigem `loja_id`; `admin` e cliente (sem `papel`) não podem ter `loja_id`. Claims incoerentes dão 401.
- Erros: 401 (token ausente ou inválido, com `WWW-Authenticate: Bearer`), 403 (papel ou loja sem permissão), 503 (JWKS ou configuração indisponível). Mensagens em português, sem vazar detalhe interno.
- A trava só atua com `AUTENTICACAO_OBRIGATORIA=true`; `SUPABASE_URL` passa a ser obrigatória nesse caso (falha na criação do `Settings`).
- Prefixos reais das rotas: `/admin`, `/atendimentos`, `/compras`, `/estoques`, `/movimentacoes-estoque`. `/health` nunca é travado.
- Testes sem banco e sem rede: nunca ler o `.env` real (`Settings(_env_file=None, ...)`), nunca chamar o Supabase.
- Commits terminam com a linha `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

---

### Task 1: Ferramentas de desenvolvimento e linha de base

**Files:**
- Create: `requirements-dev.txt`
- Create: `ruff.toml`

O `requirements.txt` cita um `requirements-dev.txt` que não existe, e `pytest` e `ruff` não estão instalados no `.venv`.

**Interfaces:**
- Produces: `pytest`, `ruff`, `bandit` e `pip-audit` disponíveis em `.venv`; linha de base dos testes conhecida.

- [ ] **Step 1: Criar `requirements-dev.txt`**

```text
# Dependencias de desenvolvimento (testes, lint, seguranca).
# Instalar: pip install -r requirements-dev.txt
-r requirements.txt

pytest>=8.0.0,<9.0.0
ruff>=0.6.0
bandit>=1.7.0
pip-audit>=2.7.0
```

- [ ] **Step 2: Criar `ruff.toml`**

```toml
line-length = 100
target-version = "py312"

[lint]
select = ["E", "F", "I", "B", "UP"]
```

- [ ] **Step 3: Instalar e rodar a linha de base**

Run: `.venv/Scripts/python.exe -m pip install -r requirements-dev.txt && .venv/Scripts/python.exe -m pytest -q`
Expected: instalação sem erro; todos os testes existentes passam. **Anote a contagem** ("N passed"). Se algum teste existente falhar, pare e reporte antes de seguir: não é falha deste plano.

- [ ] **Step 4: Commit**

```bash
git add requirements-dev.txt ruff.toml
git commit -m "chore(dev): adiciona requirements-dev e configuracao do ruff" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Flag `AUTENTICACAO_OBRIGATORIA` em `Settings`

**Files:**
- Modify: `app/core/config.py`
- Modify: `.env.example`
- Create: `tests/core/test_config_autenticacao.py`

**Interfaces:**
- Produces: `Settings.autenticacao_obrigatoria: bool` (padrão `False`). Com `True`, `Settings.supabase_url` precisa estar preenchida, senão `ValidationError`.

- [ ] **Step 1: Escrever os testes que falham**

Criar `tests/core/test_config_autenticacao.py`:

```python
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from tests.conftest import DATABASE_URL_TESTE

VARIAVEIS = ["DATABASE_URL", "SUPABASE_URL", "CORS_ORIGINS", "AUTENTICACAO_OBRIGATORIA"]


@pytest.fixture(autouse=True)
def ambiente_limpo(monkeypatch):
    for nome in VARIAVEIS:
        monkeypatch.delenv(nome, raising=False)


def criar(**valores) -> Settings:
    valores.setdefault("database_url", DATABASE_URL_TESTE)
    return Settings(_env_file=None, **valores)


def test_autenticacao_vem_desligada_por_padrao():
    assert criar().autenticacao_obrigatoria is False


def test_le_a_flag_do_ambiente(monkeypatch):
    monkeypatch.setenv("AUTENTICACAO_OBRIGATORIA", "true")
    monkeypatch.setenv("SUPABASE_URL", "https://abc.supabase.co")
    assert criar().autenticacao_obrigatoria is True


def test_flag_ligada_exige_supabase_url():
    with pytest.raises(ValidationError) as erro:
        criar(autenticacao_obrigatoria=True)
    assert "SUPABASE_URL" in str(erro.value)


def test_flag_ligada_com_supabase_url_e_aceita():
    settings = criar(autenticacao_obrigatoria=True, supabase_url="https://abc.supabase.co/")
    assert settings.autenticacao_obrigatoria is True
    assert settings.supabase_url == "https://abc.supabase.co"


def test_flag_desligada_nao_exige_supabase_url():
    assert criar(autenticacao_obrigatoria=False).supabase_url is None
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/Scripts/python.exe -m pytest tests/core/test_config_autenticacao.py -q`
Expected: FAIL (`AttributeError` ou `ValidationError` por campo desconhecido: `autenticacao_obrigatoria` não existe).

- [ ] **Step 3: Implementar em `app/core/config.py`**

Trocar os imports do topo:

```python
from typing import Annotated, Self

from fastapi import Request
from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
```

Acrescentar o campo logo abaixo de `cors_origins`:

```python
    cors_origins: Annotated[list[str], NoDecode] = []
    # Liga a trava de autenticacao em app/api/router.py. Desligada por padrao enquanto o
    # front do cliente ainda nao envia o JWT do Supabase.
    autenticacao_obrigatoria: bool = False
```

Acrescentar o validador depois de `_separar_origens`:

```python
    @model_validator(mode="after")
    def _exigir_supabase_url_com_autenticacao(self) -> Self:
        if self.autenticacao_obrigatoria and not self.supabase_url:
            raise ValueError(
                "SUPABASE_URL e obrigatoria quando AUTENTICACAO_OBRIGATORIA esta ligada"
            )
        return self
```

- [ ] **Step 4: Documentar no `.env.example`**

Acrescentar ao final do arquivo:

```text
# Exige JWT do Supabase nas rotas (true/false). Com true, SUPABASE_URL e obrigatoria.
# Deixe false enquanto o front nao enviar o token.
AUTENTICACAO_OBRIGATORIA=false
```

- [ ] **Step 5: Rodar e ver passar (e nada quebrar)**

Run: `.venv/Scripts/python.exe -m pytest tests/core -q`
Expected: PASS, incluindo `test_config.py`.

- [ ] **Step 6: Commit**

```bash
git add app/core/config.py .env.example tests/core/test_config_autenticacao.py
git commit -m "feat(core): adiciona flag AUTENTICACAO_OBRIGATORIA ao Settings" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Papéis, usuário atual e erros de autenticação

**Files:**
- Create: `app/core/papeis.py`
- Create: `app/core/erros_auth.py`
- Create: `tests/core/test_papeis.py`
- Create: `tests/core/test_erros_auth.py`

**Interfaces:**
- Produces:
  - `Papel(StrEnum)`: `ATENDENTE`, `OPERADOR_ESTOQUE`, `GERENTE_LOJA`, `ADMIN` (valores `"atendente"`, `"operador_estoque"`, `"gerente_loja"`, `"admin"`).
  - `PAPEIS_COM_LOJA: frozenset[Papel]` = atendente, operador_estoque, gerente_loja.
  - `UsuarioAtual` (pydantic, `frozen=True`): `id_auth: UUID`, `papel: Papel | None = None`, `id_loja: UUID | None = None`, método `pode_acessar_loja(self, id_loja: UUID) -> bool`.
  - `NaoAutenticado(HTTPException)` (401, `WWW-Authenticate: Bearer`, sem argumentos), `SemPermissao(ErroDeNegocio)` (403), `AutenticacaoIndisponivel(ErroDeNegocio)` (503).

- [ ] **Step 1: Escrever os testes que falham**

Criar `tests/core/test_papeis.py`:

```python
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.papeis import PAPEIS_COM_LOJA, Papel, UsuarioAtual


def test_valores_dos_papeis():
    assert {papel.value for papel in Papel} == {
        "atendente",
        "operador_estoque",
        "gerente_loja",
        "admin",
    }


def test_admin_nao_pertence_a_papeis_com_loja():
    assert Papel.ADMIN not in PAPEIS_COM_LOJA
    assert PAPEIS_COM_LOJA == {Papel.ATENDENTE, Papel.OPERADOR_ESTOQUE, Papel.GERENTE_LOJA}


def test_admin_acessa_qualquer_loja():
    usuario = UsuarioAtual(id_auth=uuid4(), papel=Papel.ADMIN)
    assert usuario.pode_acessar_loja(uuid4()) is True


def test_gerente_acessa_so_a_propria_loja():
    loja = uuid4()
    usuario = UsuarioAtual(id_auth=uuid4(), papel=Papel.GERENTE_LOJA, id_loja=loja)
    assert usuario.pode_acessar_loja(loja) is True
    assert usuario.pode_acessar_loja(uuid4()) is False


def test_cliente_nao_acessa_loja_nenhuma():
    usuario = UsuarioAtual(id_auth=uuid4())
    assert usuario.papel is None
    assert usuario.pode_acessar_loja(uuid4()) is False


def test_usuario_atual_e_imutavel():
    usuario = UsuarioAtual(id_auth=uuid4())
    with pytest.raises(ValidationError):
        usuario.papel = Papel.ADMIN
```

Criar `tests/core/test_erros_auth.py`:

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.erros import registrar_tratadores
from app.core.erros_auth import AutenticacaoIndisponivel, NaoAutenticado, SemPermissao


def montar_cliente(erro: Exception) -> TestClient:
    app = FastAPI()
    registrar_tratadores(app)

    @app.get("/falha")
    def falha():
        raise erro

    return TestClient(app)


def test_nao_autenticado_responde_401_com_cabecalho():
    resposta = montar_cliente(NaoAutenticado()).get("/falha")
    assert resposta.status_code == 401
    assert resposta.headers["www-authenticate"] == "Bearer"
    assert resposta.json() == {"detail": "Token invalido ou ausente"}


def test_sem_permissao_responde_403():
    resposta = montar_cliente(SemPermissao()).get("/falha")
    assert resposta.status_code == 403
    assert resposta.json() == {"detail": "Voce nao tem permissao para esta acao"}


def test_autenticacao_indisponivel_responde_503():
    resposta = montar_cliente(AutenticacaoIndisponivel()).get("/falha")
    assert resposta.status_code == 503
    assert resposta.json() == {"detail": "Autenticacao temporariamente indisponivel"}
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/Scripts/python.exe -m pytest tests/core/test_papeis.py tests/core/test_erros_auth.py -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.core.papeis'`.

- [ ] **Step 3: Implementar `app/core/papeis.py`**

```python
"""Papeis internos e o usuario autenticado, como o backend os enxerga a partir do JWT."""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class Papel(StrEnum):
    ATENDENTE = "atendente"
    OPERADOR_ESTOQUE = "operador_estoque"
    GERENTE_LOJA = "gerente_loja"
    ADMIN = "admin"


# Papeis que pertencem a uma loja (CLAUDE.md, secao 3). Admin tem loja nula; cliente nao tem papel.
PAPEIS_COM_LOJA = frozenset({Papel.ATENDENTE, Papel.OPERADOR_ESTOQUE, Papel.GERENTE_LOJA})


class UsuarioAtual(BaseModel):
    """Usuario do token. Cliente tem `papel=None`; admin tem `id_loja=None`."""

    model_config = ConfigDict(frozen=True)

    id_auth: UUID
    papel: Papel | None = None
    id_loja: UUID | None = None

    def pode_acessar_loja(self, id_loja: UUID) -> bool:
        if self.papel is Papel.ADMIN:
            return True
        return self.papel in PAPEIS_COM_LOJA and self.id_loja == id_loja
```

- [ ] **Step 4: Implementar `app/core/erros_auth.py`**

```python
"""Erros de autenticacao e autorizacao (CLAUDE.md, secoes 6 e 12.6)."""

from fastapi import HTTPException, status

from app.core.erros import ErroDeNegocio


class NaoAutenticado(HTTPException):
    """401. Usa HTTPException porque a resposta precisa do cabecalho WWW-Authenticate."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalido ou ausente",
            headers={"WWW-Authenticate": "Bearer"},
        )


class SemPermissao(ErroDeNegocio):
    status_code = status.HTTP_403_FORBIDDEN
    detalhe = "Voce nao tem permissao para esta acao"


class AutenticacaoIndisponivel(ErroDeNegocio):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    detalhe = "Autenticacao temporariamente indisponivel"
```

- [ ] **Step 5: Rodar e ver passar**

Run: `.venv/Scripts/python.exe -m pytest tests/core/test_papeis.py tests/core/test_erros_auth.py -q`
Expected: PASS (9 testes).

- [ ] **Step 6: Commit**

```bash
git add app/core/papeis.py app/core/erros_auth.py tests/core/test_papeis.py tests/core/test_erros_auth.py
git commit -m "feat(core): adiciona papeis, usuario atual e erros de autenticacao" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Cache de chaves públicas (`ProvedorChaves`) e utilitário de testes

**Files:**
- Create: `app/core/jwks.py`
- Create: `tests/auth_util.py`
- Create: `tests/core/test_jwks.py`

**Interfaces:**
- Consumes: `NaoAutenticado`, `AutenticacaoIndisponivel` (Task 3).
- Produces:
  - `ProvedorChaves(url_jwks: str, *, buscar: Callable[[], dict] | None = None, relogio: Callable[[], float] = time.monotonic, intervalo_minimo: float = 60.0)`.
  - `ProvedorChaves.obter_chave(kid: object) -> object`: devolve a chave pública (objeto `cryptography`) do `kid`. `kid` ausente ou não-`str` → `NaoAutenticado` sem buscar. `kid` desconhecido → rebusca no máximo 1 vez por `intervalo_minimo`; se continuar desconhecido → `NaoAutenticado`. Falha de rede, resposta inválida ou sem chaves ES256 → `AutenticacaoIndisponivel`.
  - `tests/auth_util.py`: `ISSUER`, `SUPABASE_URL`, `URL_JWKS`, `REMOVER`, `ParDeChaves(kid="chave-de-teste")` com `.kid`, `.privada`, `.jwk` (dict público) e `.emitir(**claims) -> str`, e `provedor_para(par) -> ProvedorChaves`.

- [ ] **Step 1: Criar o utilitário de testes `tests/auth_util.py`**

```python
"""Apoio dos testes de autenticacao: chaves ES256 de mentira e emissao de tokens."""

import time
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from jwt.algorithms import ECAlgorithm

from app.core.jwks import ProvedorChaves

SUPABASE_URL = "https://projeto-teste.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"
URL_JWKS = f"{ISSUER}/.well-known/jwks.json"
KID_PADRAO = "chave-de-teste"

# Valor que, passado a `emitir`, remove a claim do token.
REMOVER = object()


class ParDeChaves:
    def __init__(self, kid: str = KID_PADRAO) -> None:
        self.kid = kid
        self.privada = ec.generate_private_key(ec.SECP256R1())

    @property
    def jwk(self) -> dict:
        publica = ECAlgorithm.to_jwk(self.privada.public_key(), as_dict=True)
        return {**publica, "kid": self.kid, "alg": "ES256", "use": "sig"}

    def emitir(self, **claims) -> str:
        agora = int(time.time())
        payload = {
            "sub": str(uuid4()),
            "aud": "authenticated",
            "iss": ISSUER,
            "role": "authenticated",
            "iat": agora,
            "exp": agora + 900,
        }
        payload.update(claims)
        payload = {nome: valor for nome, valor in payload.items() if valor is not REMOVER}
        return jwt.encode(payload, self.privada, algorithm="ES256", headers={"kid": self.kid})


def provedor_para(par: ParDeChaves) -> ProvedorChaves:
    return ProvedorChaves(URL_JWKS, buscar=lambda: {"keys": [par.jwk]})
```

- [ ] **Step 2: Escrever os testes que falham**

Criar `tests/core/test_jwks.py`:

```python
import httpx
import pytest

from app.core.erros_auth import AutenticacaoIndisponivel, NaoAutenticado
from app.core.jwks import ProvedorChaves
from tests.auth_util import URL_JWKS, ParDeChaves


class Relogio:
    def __init__(self) -> None:
        self.agora = 1000.0

    def __call__(self) -> float:
        return self.agora


def provedor_com(buscar, relogio=None) -> ProvedorChaves:
    return ProvedorChaves(URL_JWKS, buscar=buscar, relogio=relogio or Relogio())


def test_busca_a_chave_uma_vez_e_guarda_em_cache():
    par = ParDeChaves()
    chamadas = []

    def buscar():
        chamadas.append(1)
        return {"keys": [par.jwk]}

    provedor = provedor_com(buscar)
    assert provedor.obter_chave(par.kid) is not None
    assert provedor.obter_chave(par.kid) is not None
    assert len(chamadas) == 1


def test_kid_desconhecido_respeita_o_intervalo_minimo_entre_buscas():
    par = ParDeChaves()
    relogio = Relogio()
    chamadas = []

    def buscar():
        chamadas.append(1)
        return {"keys": [par.jwk]}

    provedor = provedor_com(buscar, relogio)
    with pytest.raises(NaoAutenticado):
        provedor.obter_chave("desconhecida")
    with pytest.raises(NaoAutenticado):
        provedor.obter_chave("desconhecida")
    assert len(chamadas) == 1

    relogio.agora += 61
    with pytest.raises(NaoAutenticado):
        provedor.obter_chave("desconhecida")
    assert len(chamadas) == 2


def test_chave_nova_aparece_depois_da_rotacao():
    antiga, nova = ParDeChaves("antiga"), ParDeChaves("nova")
    relogio = Relogio()
    respostas = [{"keys": [antiga.jwk]}, {"keys": [antiga.jwk, nova.jwk]}]

    provedor = provedor_com(lambda: respostas.pop(0), relogio)
    assert provedor.obter_chave("antiga") is not None
    with pytest.raises(NaoAutenticado):
        provedor.obter_chave("nova")

    relogio.agora += 61
    assert provedor.obter_chave("nova") is not None


def test_falha_de_rede_vira_autenticacao_indisponivel():
    def buscar():
        raise httpx.ConnectError("sem rede")

    with pytest.raises(AutenticacaoIndisponivel):
        provedor_com(buscar).obter_chave("qualquer")


@pytest.mark.parametrize("corpo", [{"keys": []}, {}, {"keys": "lixo"}, []])
def test_resposta_sem_chaves_validas_vira_autenticacao_indisponivel(corpo):
    with pytest.raises(AutenticacaoIndisponivel):
        provedor_com(lambda: corpo).obter_chave("qualquer")


@pytest.mark.parametrize("kid", [None, "", 123, ["x"]])
def test_kid_ausente_ou_invalido_e_recusado_sem_buscar(kid):
    def buscar():
        raise AssertionError("nao deveria buscar")

    with pytest.raises(NaoAutenticado):
        provedor_com(buscar).obter_chave(kid)


def test_ignora_chaves_que_nao_sao_es256():
    par = ParDeChaves()
    simetrica = {"kty": "oct", "kid": "hmac", "k": "YWJj"}
    provedor = provedor_com(lambda: {"keys": [simetrica, par.jwk]})
    assert provedor.obter_chave(par.kid) is not None
    with pytest.raises(NaoAutenticado):
        provedor.obter_chave("hmac")
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `.venv/Scripts/python.exe -m pytest tests/core/test_jwks.py -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.core.jwks'`.

- [ ] **Step 4: Implementar `app/core/jwks.py`**

```python
"""Cache das chaves publicas (JWKS) com que o Supabase assina os tokens (ES256)."""

import threading
import time
from collections.abc import Callable

import httpx
from jwt import PyJWK, PyJWTError

from app.core.erros_auth import AutenticacaoIndisponivel, NaoAutenticado

TIMEOUT_BUSCA_SEGUNDOS = 5.0


class ProvedorChaves:
    """Guarda as chaves por `kid` e so rebusca o JWKS quando aparece um `kid` desconhecido.

    A rebusca acontece no maximo uma vez por `intervalo_minimo` (mesmo que a busca falhe),
    para um token com `kid` forjado nao virar uma enxurrada de requisicoes ao Supabase.
    """

    def __init__(
        self,
        url_jwks: str,
        *,
        buscar: Callable[[], object] | None = None,
        relogio: Callable[[], float] = time.monotonic,
        intervalo_minimo: float = 60.0,
    ) -> None:
        self._url = url_jwks
        self._buscar = buscar or self._buscar_http
        self._relogio = relogio
        self._intervalo_minimo = intervalo_minimo
        self._chaves: dict[str, PyJWK] = {}
        self._ultima_busca: float | None = None
        self._trava = threading.Lock()

    def obter_chave(self, kid: object) -> object:
        if not isinstance(kid, str) or not kid:
            raise NaoAutenticado()
        chave = self._chaves.get(kid)
        if chave is None:
            with self._trava:
                chave = self._chaves.get(kid)
                if chave is None and self._pode_buscar():
                    self._atualizar()
                    chave = self._chaves.get(kid)
        if chave is None:
            raise NaoAutenticado()
        return chave.key

    def _pode_buscar(self) -> bool:
        if self._ultima_busca is None:
            return True
        return self._relogio() - self._ultima_busca >= self._intervalo_minimo

    def _atualizar(self) -> None:
        self._ultima_busca = self._relogio()
        try:
            brutas = self._buscar()["keys"]
            iterator = iter(brutas)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as erro:
            raise AutenticacaoIndisponivel() from erro

        novas: dict[str, PyJWK] = {}
        for bruta in iterator:
            if not isinstance(bruta, dict):
                continue
            if bruta.get("kty") != "EC" or bruta.get("alg", "ES256") != "ES256":
                continue
            kid = bruta.get("kid")
            if not isinstance(kid, str) or not kid:
                continue
            try:
                novas[kid] = PyJWK.from_dict(bruta, algorithm="ES256")
            except (PyJWTError, ValueError, TypeError):
                continue
        if not novas:
            raise AutenticacaoIndisponivel()
        self._chaves = novas

    def _buscar_http(self) -> object:
        resposta = httpx.get(self._url, timeout=TIMEOUT_BUSCA_SEGUNDOS)
        resposta.raise_for_status()
        return resposta.json()
```

- [ ] **Step 5: Rodar e ver passar**

Run: `.venv/Scripts/python.exe -m pytest tests/core/test_jwks.py -q`
Expected: PASS (13 testes). Se `{"keys": "lixo"}` ou `[]` não virarem `AutenticacaoIndisponivel`, corrija o `try` de `_atualizar` (a chave `["keys"]` de uma lista levanta `TypeError`, e `iter("lixo")` não falha, mas nenhuma entrada é `dict`, então `novas` fica vazio e dispara a exceção).

- [ ] **Step 6: Commit**

```bash
git add app/core/jwks.py tests/auth_util.py tests/core/test_jwks.py
git commit -m "feat(core): adiciona cache de chaves publicas do Supabase (JWKS)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Decodificação e validação do JWT

**Files:**
- Create: `app/core/security.py`
- Create: `tests/core/test_security_jwt.py`

**Interfaces:**
- Consumes: `ProvedorChaves.obter_chave`, `Papel`, `PAPEIS_COM_LOJA`, `UsuarioAtual`, `NaoAutenticado`; de `tests/auth_util.py`: `ParDeChaves`, `provedor_para`, `ISSUER`, `REMOVER`.
- Produces: `decodificar_token(token: str, *, provedor: ProvedorChaves, issuer: str) -> UsuarioAtual`, constantes `ALGORITMO = "ES256"`, `AUDIENCE = "authenticated"`, `TAMANHO_MAXIMO_TOKEN = 8192`. Qualquer falha de validação levanta `NaoAutenticado`; indisponibilidade do JWKS propaga `AutenticacaoIndisponivel`.

- [ ] **Step 1: Escrever os testes que falham**

Criar `tests/core/test_security_jwt.py`:

```python
import base64
import json
import time
from uuid import UUID, uuid4

import jwt
import pytest

from app.core.erros_auth import NaoAutenticado
from app.core.papeis import Papel, UsuarioAtual
from app.core.security import TAMANHO_MAXIMO_TOKEN, decodificar_token
from tests.auth_util import ISSUER, REMOVER, ParDeChaves, provedor_para


@pytest.fixture
def par() -> ParDeChaves:
    return ParDeChaves()


@pytest.fixture
def provedor(par):
    return provedor_para(par)


def validar(token, provedor) -> UsuarioAtual:
    return decodificar_token(token, provedor=provedor, issuer=ISSUER)


def adulterar(token: str, **claims) -> str:
    cabecalho, corpo, assinatura = token.split(".")
    dados = json.loads(base64.urlsafe_b64decode(corpo + "=" * (-len(corpo) % 4)))
    dados.update(claims)
    novo = base64.urlsafe_b64encode(json.dumps(dados).encode()).rstrip(b"=").decode()
    return ".".join([cabecalho, novo, assinatura])


# ---- tokens validos ----------------------------------------------------------------------


def test_cliente_nao_tem_papel_nem_loja(par, provedor):
    sub = uuid4()
    usuario = validar(par.emitir(sub=str(sub)), provedor)
    assert usuario == UsuarioAtual(id_auth=sub)


def test_gerente_traz_papel_e_loja(par, provedor):
    sub, loja = uuid4(), uuid4()
    token = par.emitir(sub=str(sub), papel="gerente_loja", loja_id=str(loja))
    usuario = validar(token, provedor)
    assert usuario == UsuarioAtual(id_auth=sub, papel=Papel.GERENTE_LOJA, id_loja=loja)


def test_admin_nao_tem_loja(par, provedor):
    usuario = validar(par.emitir(papel="admin"), provedor)
    assert usuario.papel is Papel.ADMIN
    assert usuario.id_loja is None


# ---- ataques e tokens quebrados ----------------------------------------------------------


def test_token_expirado(par, provedor):
    with pytest.raises(NaoAutenticado):
        validar(par.emitir(exp=int(time.time()) - 10), provedor)


def test_audience_errada(par, provedor):
    with pytest.raises(NaoAutenticado):
        validar(par.emitir(aud="outro-publico"), provedor)


def test_issuer_errado(par, provedor):
    with pytest.raises(NaoAutenticado):
        validar(par.emitir(iss="https://invasor.example/auth/v1"), provedor)


@pytest.mark.parametrize("claim", ["exp", "sub", "aud", "iss"])
def test_claim_obrigatoria_ausente(par, provedor, claim):
    with pytest.raises(NaoAutenticado):
        validar(par.emitir(**{claim: REMOVER}), provedor)


def test_algoritmo_none_e_recusado(par, provedor):
    payload = {
        "sub": str(uuid4()),
        "aud": "authenticated",
        "iss": ISSUER,
        "exp": int(time.time()) + 900,
    }
    token = jwt.encode(payload, key=None, algorithm="none", headers={"kid": par.kid})
    with pytest.raises(NaoAutenticado):
        validar(token, provedor)


def test_algoritmo_hs256_e_recusado(par, provedor):
    payload = {
        "sub": str(uuid4()),
        "aud": "authenticated",
        "iss": ISSUER,
        "role": "authenticated",
        "exp": int(time.time()) + 900,
    }
    segredo = "um-segredo-qualquer-com-mais-de-trinta-e-dois-bytes"
    token = jwt.encode(payload, segredo, algorithm="HS256", headers={"kid": par.kid})
    with pytest.raises(NaoAutenticado):
        validar(token, provedor)


def test_payload_adulterado_invalida_a_assinatura(par, provedor):
    token = par.emitir(papel="atendente", loja_id=str(uuid4()))
    with pytest.raises(NaoAutenticado):
        validar(adulterar(token, papel="admin", loja_id=None), provedor)


def test_assinado_por_outra_chave_com_o_mesmo_kid(par, provedor):
    impostor = ParDeChaves(kid=par.kid)
    with pytest.raises(NaoAutenticado):
        validar(impostor.emitir(), provedor)


def test_kid_desconhecido(provedor):
    desconhecida = ParDeChaves(kid="outra-chave")
    with pytest.raises(NaoAutenticado):
        validar(desconhecida.emitir(), provedor)


def test_lixo_nao_e_token(provedor):
    with pytest.raises(NaoAutenticado):
        validar("isto-nao-e-um-jwt", provedor)


def test_token_grande_demais_e_recusado_sem_decodificar(provedor):
    with pytest.raises(NaoAutenticado):
        validar("a" * (TAMANHO_MAXIMO_TOKEN + 1), provedor)


# ---- claims incoerentes ------------------------------------------------------------------


@pytest.mark.parametrize(
    "claims",
    [
        {"papel": "gerente_loja"},
        {"papel": "atendente"},
        {"papel": "operador_estoque"},
        {"papel": "admin", "loja_id": str(uuid4())},
        {"loja_id": str(uuid4())},
        {"papel": "superusuario", "loja_id": str(uuid4())},
        {"papel": ["admin"]},
        {"papel": "gerente_loja", "loja_id": "isto-nao-e-uuid"},
        {"role": "anon"},
        {"role": REMOVER},
        {"is_anonymous": True},
        {"sub": "nao-e-uuid"},
    ],
    ids=[
        "gerente-sem-loja",
        "atendente-sem-loja",
        "operador-sem-loja",
        "admin-com-loja",
        "cliente-com-loja",
        "papel-desconhecido",
        "papel-nao-string",
        "loja-invalida",
        "role-anon",
        "sem-role",
        "anonimo",
        "sub-invalido",
    ],
)
def test_claims_incoerentes_dao_401(par, provedor, claims):
    with pytest.raises(NaoAutenticado):
        validar(par.emitir(**claims), provedor)


def test_sub_e_devolvido_como_uuid(par, provedor):
    sub = uuid4()
    assert isinstance(validar(par.emitir(sub=str(sub)), provedor).id_auth, UUID)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/Scripts/python.exe -m pytest tests/core/test_security_jwt.py -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.core.security'`.

- [ ] **Step 3: Implementar `app/core/security.py` (somente a decodificação)**

```python
"""Validacao do JWT do Supabase e controle de acesso por papel (CLAUDE.md, secoes 3 e 12.7)."""

from uuid import UUID

import jwt

from app.core.erros_auth import NaoAutenticado
from app.core.jwks import ProvedorChaves
from app.core.papeis import PAPEIS_COM_LOJA, Papel, UsuarioAtual

ALGORITMO = "ES256"
AUDIENCE = "authenticated"
TAMANHO_MAXIMO_TOKEN = 8192
CLAIMS_OBRIGATORIAS = ["exp", "sub", "aud", "iss"]


def decodificar_token(token: str, *, provedor: ProvedorChaves, issuer: str) -> UsuarioAtual:
    """Valida assinatura, expiracao, audience e issuer e devolve o usuario das claims.

    Qualquer falha de validacao vira NaoAutenticado, sem dizer o motivo ao chamador.
    """
    if len(token) > TAMANHO_MAXIMO_TOKEN:
        raise NaoAutenticado()
    try:
        cabecalho = jwt.get_unverified_header(token)
        if cabecalho.get("alg") != ALGORITMO:
            raise NaoAutenticado()
        chave = provedor.obter_chave(cabecalho.get("kid"))
        claims = jwt.decode(
            token,
            chave,
            algorithms=[ALGORITMO],
            audience=AUDIENCE,
            issuer=issuer,
            options={"require": CLAIMS_OBRIGATORIAS},
        )
    except jwt.PyJWTError as erro:
        raise NaoAutenticado() from erro
    return _usuario_das_claims(claims)


def _usuario_das_claims(claims: dict) -> UsuarioAtual:
    if claims.get("is_anonymous") is True or claims.get("role") != "authenticated":
        raise NaoAutenticado()
    try:
        id_auth = UUID(str(claims["sub"]))
        papel_bruto = claims.get("papel")
        papel = Papel(papel_bruto) if papel_bruto is not None else None
        loja_bruta = claims.get("loja_id")
        id_loja = UUID(str(loja_bruta)) if loja_bruta is not None else None
    except (ValueError, TypeError, KeyError) as erro:
        raise NaoAutenticado() from erro

    # Papel de loja exige loja; admin e cliente nao podem ter loja.
    if (papel in PAPEIS_COM_LOJA) != (id_loja is not None):
        raise NaoAutenticado()
    return UsuarioAtual(id_auth=id_auth, papel=papel, id_loja=id_loja)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/Scripts/python.exe -m pytest tests/core/test_security_jwt.py -q`
Expected: PASS (30 testes). Atenção a dois casos que costumam falhar na primeira tentativa: (a) `{"papel": ["admin"]}` precisa virar `NaoAutenticado` (o `Papel(...)` com lista levanta `ValueError` ou `TypeError`, ambos capturados); (b) `test_algoritmo_none_e_recusado` precisa da recusa **antes** da busca de chave (o cabeçalho `alg` é checado primeiro).

- [ ] **Step 5: Commit**

```bash
git add app/core/security.py tests/core/test_security_jwt.py
git commit -m "feat(core): valida o JWT do Supabase (ES256) e extrai papel e loja" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Dependências do FastAPI, trava por flag e ligação nas rotas

**Files:**
- Modify: `app/core/security.py` (acrescentar dependências)
- Modify: `app/api/router.py`
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-10-06-auth-rls-sobre-intermediaria-design.md` (corrigir o prefixo de movimentações)
- Create: `tests/core/test_security_dependencias.py`
- Create: `tests/api/test_trava_rotas.py`

**Interfaces:**
- Consumes: tudo das Tasks 3 a 5.
- Produces (em `app/core/security.py`):
  - `get_current_user(request: Request, credenciais) -> UsuarioAtual` (dependência).
  - `requer_papel(*papeis: Papel)` → dependência que devolve `UsuarioAtual` ou levanta `SemPermissao`.
  - `garantir_escopo_de_loja(usuario: UsuarioAtual, id_loja: UUID) -> None` (levanta `SemPermissao`).
  - `trava(*papeis: Papel)` → dependência sem retorno; **sem efeito** com `autenticacao_obrigatoria=False`; com `True` exige token válido e, se `papeis` não for vazio, um desses papéis.
  - O provedor de chaves é lido de `app.state.provedor_chaves` e criado sob demanda a partir de `settings.supabase_url`.

- [ ] **Step 1: Escrever os testes das dependências (falham)**

Criar `tests/core/test_security_dependencias.py`:

```python
from typing import Annotated
from uuid import uuid4

import httpx
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.erros import registrar_tratadores
from app.core.erros_auth import SemPermissao
from app.core.jwks import ProvedorChaves
from app.core.papeis import Papel, UsuarioAtual
from app.core.security import garantir_escopo_de_loja, get_current_user, requer_papel, trava
from tests.auth_util import SUPABASE_URL, URL_JWKS, ParDeChaves, provedor_para
from tests.conftest import DATABASE_URL_TESTE


def montar_app(par: ParDeChaves, *, obrigatoria: bool = True, provedor=None) -> FastAPI:
    settings = Settings(
        _env_file=None,
        database_url=DATABASE_URL_TESTE,
        supabase_url=SUPABASE_URL,
        autenticacao_obrigatoria=obrigatoria,
    )
    app = FastAPI()
    app.state.settings = settings
    app.state.provedor_chaves = provedor or provedor_para(par)
    registrar_tratadores(app)

    @app.get("/eu")
    def eu(usuario: Annotated[UsuarioAtual, Depends(get_current_user)]):
        return {"id": str(usuario.id_auth), "papel": usuario.papel}

    @app.get("/so-gerente", dependencies=[Depends(requer_papel(Papel.GERENTE_LOJA, Papel.ADMIN))])
    def so_gerente():
        return {"ok": True}

    @app.get("/travada-admin", dependencies=[Depends(trava(Papel.ADMIN))])
    def travada_admin():
        return {"ok": True}

    @app.get("/travada-qualquer", dependencies=[Depends(trava())])
    def travada_qualquer():
        return {"ok": True}

    return app


def cabecalho(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def par() -> ParDeChaves:
    return ParDeChaves()


@pytest.fixture
def cliente(par) -> TestClient:
    return TestClient(montar_app(par))


# ---- get_current_user --------------------------------------------------------------------


def test_sem_cabecalho_responde_401(cliente):
    resposta = cliente.get("/eu")
    assert resposta.status_code == 401
    assert resposta.headers["www-authenticate"] == "Bearer"


def test_esquema_diferente_de_bearer_responde_401(cliente):
    assert cliente.get("/eu", headers={"Authorization": "Basic YWJjOmRlZg=="}).status_code == 401


def test_token_valido_devolve_o_usuario(cliente, par):
    sub = uuid4()
    resposta = cliente.get("/eu", headers=cabecalho(par.emitir(sub=str(sub))))
    assert resposta.status_code == 200
    assert resposta.json() == {"id": str(sub), "papel": None}


def test_token_invalido_nao_vaza_o_motivo(cliente):
    resposta = cliente.get("/eu", headers=cabecalho("lixo"))
    assert resposta.status_code == 401
    assert resposta.json() == {"detail": "Token invalido ou ausente"}


def test_jwks_fora_do_ar_responde_503(par):
    def buscar():
        raise httpx.ConnectError("sem rede")

    app = montar_app(par, provedor=ProvedorChaves(URL_JWKS, buscar=buscar))
    resposta = TestClient(app).get("/eu", headers=cabecalho(par.emitir()))
    assert resposta.status_code == 503


def test_sem_supabase_url_responde_503(par):
    app = montar_app(par, obrigatoria=False)
    del app.state.provedor_chaves
    app.state.settings = Settings(_env_file=None, database_url=DATABASE_URL_TESTE)
    resposta = TestClient(app).get("/eu", headers=cabecalho(par.emitir()))
    assert resposta.status_code == 503


# ---- requer_papel ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("claims", "esperado"),
    [
        ({}, 403),
        ({"papel": "atendente", "loja_id": str(uuid4())}, 403),
        ({"papel": "gerente_loja", "loja_id": str(uuid4())}, 200),
        ({"papel": "admin"}, 200),
    ],
    ids=["cliente", "atendente", "gerente", "admin"],
)
def test_requer_papel(cliente, par, claims, esperado):
    resposta = cliente.get("/so-gerente", headers=cabecalho(par.emitir(**claims)))
    assert resposta.status_code == esperado


def test_requer_papel_sem_token_responde_401(cliente):
    assert cliente.get("/so-gerente").status_code == 401


# ---- trava -------------------------------------------------------------------------------


def test_trava_desligada_nao_bloqueia_nada(par):
    cliente = TestClient(montar_app(par, obrigatoria=False))
    assert cliente.get("/travada-admin").status_code == 200
    assert cliente.get("/travada-qualquer").status_code == 200


def test_trava_ligada_sem_token_responde_401(cliente):
    assert cliente.get("/travada-admin").status_code == 401
    assert cliente.get("/travada-qualquer").status_code == 401


def test_trava_ligada_respeita_o_papel(cliente, par):
    assert cliente.get("/travada-admin", headers=cabecalho(par.emitir())).status_code == 403
    assert (
        cliente.get("/travada-admin", headers=cabecalho(par.emitir(papel="admin"))).status_code
        == 200
    )


def test_trava_sem_papeis_aceita_qualquer_usuario_autenticado(cliente, par):
    assert cliente.get("/travada-qualquer", headers=cabecalho(par.emitir())).status_code == 200


# ---- escopo de loja ----------------------------------------------------------------------


def test_garantir_escopo_de_loja():
    loja = uuid4()
    gerente = UsuarioAtual(id_auth=uuid4(), papel=Papel.GERENTE_LOJA, id_loja=loja)
    garantir_escopo_de_loja(gerente, loja)
    with pytest.raises(SemPermissao):
        garantir_escopo_de_loja(gerente, uuid4())
    garantir_escopo_de_loja(UsuarioAtual(id_auth=uuid4(), papel=Papel.ADMIN), uuid4())
    with pytest.raises(SemPermissao):
        garantir_escopo_de_loja(UsuarioAtual(id_auth=uuid4()), loja)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/Scripts/python.exe -m pytest tests/core/test_security_dependencias.py -q`
Expected: FAIL com `ImportError: cannot import name 'garantir_escopo_de_loja' from 'app.core.security'`.

- [ ] **Step 3: Acrescentar as dependências a `app/core/security.py`**

Trocar os imports do topo por:

```python
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.erros_auth import AutenticacaoIndisponivel, NaoAutenticado, SemPermissao
from app.core.jwks import ProvedorChaves
from app.core.papeis import PAPEIS_COM_LOJA, Papel, UsuarioAtual
```

Acrescentar ao final do arquivo:

```python
_esquema_bearer = HTTPBearer(auto_error=False, description="JWT do Supabase Auth")
CredenciaisDep = Annotated[HTTPAuthorizationCredentials | None, Depends(_esquema_bearer)]


def _provedor(request: Request) -> ProvedorChaves:
    provedor = getattr(request.app.state, "provedor_chaves", None)
    if provedor is None:
        provedor = ProvedorChaves(
            f"{request.app.state.settings.supabase_url}/auth/v1/.well-known/jwks.json"
        )
        request.app.state.provedor_chaves = provedor
    return provedor


def _autenticar(
    request: Request,
    credenciais: HTTPAuthorizationCredentials | None,
) -> UsuarioAtual:
    supabase_url = request.app.state.settings.supabase_url
    if not supabase_url:
        raise AutenticacaoIndisponivel()
    if credenciais is None:
        raise NaoAutenticado()
    return decodificar_token(
        credenciais.credentials,
        provedor=_provedor(request),
        issuer=f"{supabase_url}/auth/v1",
    )


def get_current_user(request: Request, credenciais: CredenciaisDep) -> UsuarioAtual:
    """Dependencia: o usuario do token, ou 401 (ou 503 se a autenticacao estiver indisponivel)."""
    return _autenticar(request, credenciais)


def requer_papel(*papeis: Papel):
    """Fabrica de dependencia: exige um dos papeis e devolve o usuario (403 se nao tiver)."""
    permitidos = frozenset(papeis)

    def dependencia(usuario: Annotated[UsuarioAtual, Depends(get_current_user)]) -> UsuarioAtual:
        if usuario.papel not in permitidos:
            raise SemPermissao()
        return usuario

    return dependencia


def garantir_escopo_de_loja(usuario: UsuarioAtual, id_loja: UUID) -> None:
    """Admin acessa qualquer loja; os demais so a propria (CLAUDE.md, secao 7)."""
    if not usuario.pode_acessar_loja(id_loja):
        raise SemPermissao()


def trava(*papeis: Papel):
    """Dependencia de modulo, controlada por AUTENTICACAO_OBRIGATORIA.

    Desligada, nao faz nada (a tela do cliente continua funcionando sem token). Ligada,
    exige token valido e, se `papeis` nao for vazio, um desses papeis; vazio aceita
    qualquer usuario autenticado.
    """
    permitidos = frozenset(papeis)

    def dependencia(request: Request, credenciais: CredenciaisDep) -> None:
        if not request.app.state.settings.autenticacao_obrigatoria:
            return
        usuario = _autenticar(request, credenciais)
        if permitidos and usuario.papel not in permitidos:
            raise SemPermissao()

    return dependencia
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/Scripts/python.exe -m pytest tests/core/test_security_dependencias.py tests/core/test_security_jwt.py -q`
Expected: PASS. Se `test_sem_supabase_url_responde_503` falhar por `KeyError` ao apagar `provedor_chaves`, troque `del app.state.provedor_chaves` por `app.state.provedor_chaves = None`.

- [ ] **Step 5: Escrever os testes de integração da trava (falham)**

Criar `tests/api/test_trava_rotas.py`:

```python
"""A trava ligada em app/api/router.py, sem banco: o executor devolve lista vazia."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.db import get_executar
from app.core.papeis import Papel
from app.main import criar_app
from tests.auth_util import SUPABASE_URL, ParDeChaves, provedor_para
from tests.conftest import DATABASE_URL_TESTE

EQUIPE_DE_ESTOQUE = {Papel.OPERADOR_ESTOQUE, Papel.GERENTE_LOJA, Papel.ADMIN}
TODOS = {None, *Papel}

# (caminho, quem pode)
ROTAS = [
    ("/admin/lojas", {Papel.ADMIN}),
    ("/estoques", EQUIPE_DE_ESTOQUE),
    ("/movimentacoes-estoque", EQUIPE_DE_ESTOQUE),
    ("/atendimentos", TODOS),
    ("/compras/pedidos", TODOS),
]
CASOS = [(caminho, papel) for caminho, _quem in ROTAS for papel in (None, *Papel)]


def montar(obrigatoria: bool):
    par = ParDeChaves()
    app = criar_app(
        Settings(
            _env_file=None,
            database_url=DATABASE_URL_TESTE,
            supabase_url=SUPABASE_URL,
            autenticacao_obrigatoria=obrigatoria,
        )
    )
    app.state.provedor_chaves = provedor_para(par)
    app.dependency_overrides[get_executar] = lambda: (lambda _operacao: [])
    return TestClient(app), par


def token_do_papel(par: ParDeChaves, papel: Papel | None) -> str:
    if papel is None:
        return par.emitir()
    if papel is Papel.ADMIN:
        return par.emitir(papel="admin")
    return par.emitir(papel=papel.value, loja_id=str(uuid4()))


@pytest.mark.parametrize("caminho", [caminho for caminho, _ in ROTAS])
def test_com_a_flag_desligada_nada_exige_token(caminho):
    cliente, _par = montar(obrigatoria=False)
    assert cliente.get(caminho).status_code == 200


@pytest.mark.parametrize("caminho", [caminho for caminho, _ in ROTAS])
def test_com_a_flag_ligada_sem_token_responde_401(caminho):
    cliente, _par = montar(obrigatoria=True)
    assert cliente.get(caminho).status_code == 401


@pytest.mark.parametrize(("caminho", "papel"), CASOS)
def test_matriz_de_papeis_com_a_flag_ligada(caminho, papel):
    permitidos = dict(ROTAS)[caminho]
    cliente, par = montar(obrigatoria=True)
    resposta = cliente.get(
        caminho, headers={"Authorization": f"Bearer {token_do_papel(par, papel)}"}
    )
    assert resposta.status_code == (200 if papel in permitidos else 403)


def test_health_nunca_e_travado():
    cliente, _par = montar(obrigatoria=True)
    assert cliente.get("/health").status_code == 200
```

- [ ] **Step 6: Rodar e ver falhar**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_trava_rotas.py -q`
Expected: FAIL: `test_com_a_flag_ligada_sem_token_responde_401` e a matriz retornam 200 (a trava ainda não está ligada em `app/api/router.py`); os testes com a flag desligada e o de `/health` já passam.

- [ ] **Step 7: Ligar a trava em `app/api/router.py`**

Substituir o conteúdo do arquivo por:

```python
"""Reune os routers de cada modulo. Um modulo novo entra aqui com uma linha."""

from fastapi import APIRouter, Depends

from app.admin.router import router as admin_router
from app.api import health
from app.atendimento.router import router as atendimento_router
from app.compras.router import router as compras_router
from app.core.papeis import Papel
from app.core.security import trava
from app.estoque.router import router as estoque_router
from app.movimentacoes.router import router as movimentacoes_router

# So atua com AUTENTICACAO_OBRIGATORIA=true (ver app/core/security.py). Barra acesso anonimo e
# papel inadequado; filtro por dono ou por loja continua dentro dos handlers de cada modulo.
EQUIPE_DE_ESTOQUE = (Papel.OPERADOR_ESTOQUE, Papel.GERENTE_LOJA, Papel.ADMIN)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(admin_router, dependencies=[Depends(trava(Papel.ADMIN))])
api_router.include_router(atendimento_router, dependencies=[Depends(trava())])
api_router.include_router(compras_router, dependencies=[Depends(trava())])
api_router.include_router(estoque_router, dependencies=[Depends(trava(*EQUIPE_DE_ESTOQUE))])
api_router.include_router(
    movimentacoes_router, dependencies=[Depends(trava(*EQUIPE_DE_ESTOQUE))]
)
```

- [ ] **Step 8: Rodar a suíte inteira**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS em tudo, e o total é a contagem anotada na Task 1 mais os testes novos. Nenhum teste existente de `admin`, `atendimento`, `compras`, `estoque` ou `movimentacoes` pode mudar de resultado (a flag é desligada por padrão).

- [ ] **Step 9: Documentar no `README.md` e corrigir o spec**

No `README.md`, acrescentar uma seção ao final:

````markdown
## Autenticação (JWT do Supabase)

O login é do Supabase Auth; a API só valida o token (`Authorization: Bearer <jwt>`), com chaves
públicas em `<SUPABASE_URL>/auth/v1/.well-known/jwks.json` (ES256).

A trava é controlada por `AUTENTICACAO_OBRIGATORIA` (padrão `false`):

| Valor | Efeito |
|---|---|
| `false` | Nenhuma rota exige token (comportamento atual, usado pela tela do cliente). |
| `true` | `/admin` exige `admin`; `/estoques` e `/movimentacoes-estoque` exigem `operador_estoque`, `gerente_loja` ou `admin`; `/atendimentos` e `/compras` exigem qualquer usuário autenticado; `/health` segue aberto. Exige `SUPABASE_URL`. |

**Limite:** a trava só barra acesso anônimo e papel inadequado. Ela não impede que um cliente logado
leia dados de outro cliente, nem que uma loja mexa na outra; esse filtro precisa ser feito dentro dos
handlers de cada módulo (ver "Fora do escopo" do spec de auth).

**Antes de ligar a flag**, o hook de claims precisa estar ativo no painel do Supabase
(Authentication → Hooks → Custom Access Token). Sem ele, todo token de equipe vem sem `papel` e a
API responde 403. O hook é entregue pelo Plano 2 (revisão Alembic de RLS e claims).
````

No spec `docs/superpowers/specs/2026-10-06-auth-rls-sobre-intermediaria-design.md`, trocar as duas ocorrências de `/movimentacoes` por `/movimentacoes-estoque` (tabela da seção 1 e texto do limite assumido, se houver):

Run: `grep -n "movimentacoes" docs/superpowers/specs/2026-10-06-auth-rls-sobre-intermediaria-design.md`
Expected: as linhas que citam a rota; edite apenas as que se referem ao caminho HTTP `/movimentacoes` (não a tabela `movimentacao_estoque` nem o módulo).

- [ ] **Step 10: Lint, segurança e verificação final**

Run:
```bash
.venv/Scripts/python.exe -m ruff check app/core/papeis.py app/core/erros_auth.py app/core/jwks.py app/core/security.py app/core/config.py app/api/router.py tests/auth_util.py tests/core/test_papeis.py tests/core/test_erros_auth.py tests/core/test_jwks.py tests/core/test_security_jwt.py tests/core/test_security_dependencias.py tests/core/test_config_autenticacao.py tests/api/test_trava_rotas.py
.venv/Scripts/python.exe -m bandit -q -r app/core
.venv/Scripts/python.exe -m pytest -q
```
Expected: `ruff` sem apontamentos (corrija ordem de imports ou linhas longas dos arquivos **novos**; não reformate arquivos de outros módulos); `bandit` sem achados; pytest todo verde. Rode também `.venv/Scripts/python.exe -m pip_audit -r requirements.txt` e **apenas reporte** o resultado ao usuário (vulnerabilidades de dependências existentes não bloqueiam este plano).

- [ ] **Step 11: Commit**

```bash
git add app/core/security.py app/api/router.py README.md docs/superpowers/specs/2026-10-06-auth-rls-sobre-intermediaria-design.md tests/core/test_security_dependencias.py tests/api/test_trava_rotas.py
git commit -m "feat(api): liga a trava de autenticacao por flag nos routers" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

## Self-Review (feito ao escrever o plano)

**Cobertura do spec, seção "1. Núcleo de auth":**
- Validação do JWT (assinatura, `exp`, `aud`, `iss`, `sub`, tamanho, `alg` ≠ ES256 e `none`): Task 5.
- JWKS em cache, com lock e rebusca limitada, `httpx` síncrono com timeout: Task 4.
- Algoritmo confirmado no projeto (JWKS, ES256): resolvido antes do plano e registrado em Global Constraints.
- `Papel`, `UsuarioAtual`, claims incoerentes dão 401: Tasks 3 e 5.
- `get_current_user`, `requer_papel`, helper de escopo de loja, 401/403 em português: Tasks 3 e 6.
- `Settings.autenticacao_obrigatoria` e `supabase_url` obrigatória com a flag ligada: Task 2.
- Trava por flag em `app/api/router.py` e a tabela de módulos × papéis: Task 6, com o prefixo real `/movimentacoes-estoque`.
- Limite assumido da trava grossa: README (Task 6) e Global Constraints.
- Testes de auth sem banco (expirado, `aud`/`iss`, `alg=none`, HS256, adulterado, `kid` desconhecido, incoerentes, matriz de `requer_papel`, 401, flag ligada/desligada): Tasks 4 a 6.
- Seções "2. Banco" e "3. Testes" do spec (RLS, hook, Docker) **não** estão aqui: são o Plano 2.

**Pontos de atenção conhecidos:**
- "Ativo" (spec: "usuário autenticado e ativo"): o token não diz se um **cliente** está inativo. Usuário de equipe inativo perde o `papel` no hook (Plano 2) e passa a ser tratado como cliente; cliente inativo precisa ser banido no Supabase Auth. Registrado no README como limite.
- O hook de claims só chega no Plano 2; até lá, com a flag ligada, tokens de equipe vêm sem `papel`.

**Consistência de tipos:** `ProvedorChaves.obter_chave(kid) -> chave` (Task 4) é consumida em `decodificar_token` (Task 5); `UsuarioAtual.pode_acessar_loja` (Task 3) é usada por `garantir_escopo_de_loja` (Task 6); `ParDeChaves.emitir`, `provedor_para`, `ISSUER`, `SUPABASE_URL`, `URL_JWKS` e `REMOVER` (Task 4) são usados nas Tasks 5 e 6; `trava` e `requer_papel` têm a mesma assinatura (`*papeis: Papel`) onde aparecem.
