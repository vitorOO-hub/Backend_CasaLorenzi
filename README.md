# Casa Lorenzi — Backend

API e banco de dados da plataforma da **Casa Lorenzi**, rede de moda com três lojas (Ibirapuera/SP,
Barra/RJ e Savassi/BH). A plataforma tem uma loja online para o cliente e um painel interno com
estoque, atendimento, gerência e gestão.

| | |
|---|---|
| **API em produção** | https://backend-casalorenzi.onrender.com (`GET /health`) |
| **Frontend** | repositório [Frontend_CasaLorenzi](https://github.com/vitorOO-hub/Frontend_CasaLorenzi) |
| **Branches** | `intermediaria` recebe todo trabalho novo; `main` é a versão publicada |

## Sumário

1. [Visão geral](#1-visão-geral)
2. [Requisitos](#2-requisitos)
3. [Como rodar](#3-como-rodar)
4. [Variáveis de ambiente](#4-variáveis-de-ambiente)
5. [Estrutura do projeto](#5-estrutura-do-projeto)
6. [Autenticação e papéis](#6-autenticação-e-papéis)
7. [API](#7-api)
8. [Banco de dados e migrations](#8-banco-de-dados-e-migrations)
9. [Segurança](#9-segurança)
10. [Testes e qualidade](#10-testes-e-qualidade)
11. [Deploy](#11-deploy)
12. [Scripts utilitários](#12-scripts-utilitários)
13. [Como contribuir](#13-como-contribuir)
14. [Problemas comuns](#14-problemas-comuns)

---

## 1. Visão geral

```text
Navegador (React, Vercel)
   │  login, sessão, chat ao vivo e anexos
   ├────────────────────────────►  Supabase (Auth, Realtime, Storage)
   │                                        ▲
   │  Authorization: Bearer <JWT>           │ valida o token (JWKS)
   └────────────────────────────►  API FastAPI (Render) ──► PostgreSQL (Supabase)
```

- **Supabase Auth** cuida de login, cadastro e emissão do JWT. A API **nunca** guarda senha nem emite token: ela só valida.
- **Papel e loja** da equipe viajam no JWT, gravados por um *Custom Access Token Hook* do banco (`public.hook_claims_token`).
- **Toda escrita passa pela API**, que usa uma conexão privilegiada (ignora RLS). Por isso a checagem de papel e de escopo de loja está no código Python, nunca só no banco.
- Direto no Supabase, o front só lê dados protegidos por RLS e insere mensagens e avaliações do próprio cliente.

**Stack:** Python 3.12 · FastAPI · SQLAlchemy Core (SQL parametrizado) · Alembic · PostgreSQL (Supabase) · PyJWT (ES256/JWKS) · pytest · ruff · bandit.

## 2. Requisitos

- Python **3.12**
- Um banco PostgreSQL (o projeto Supabase, ou um Postgres local para desenvolver)
- Para os testes de banco: PostgreSQL 15+ local (opcional, ver [seção 10](#10-testes-e-qualidade))

## 3. Como rodar

```bash
# 1. Ambiente virtual e dependências
python -m venv .venv
source .venv/bin/activate          # Windows (PowerShell): .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt

# 2. Configuração: copie o modelo e preencha (o .env nunca vai para o Git)
cp .env.example .env               # Windows: copy .env.example .env

# 3. Banco: aplica todas as migrations do Alembic
alembic upgrade head

# 4. Servidor de desenvolvimento (sempre da raiz do projeto)
uvicorn app.main:app --reload
```

A API sobe em `http://127.0.0.1:8000`. Confira:

```bash
curl http://127.0.0.1:8000/health      # {"status": "ok"}
```

Para ver a documentação interativa, ligue-a só em desenvolvimento com `DOCS_HABILITADAS=true` no `.env`
e abra `http://127.0.0.1:8000/docs`. Em produção ela fica fechada (404).

> O front espera a API em `http://localhost:8000` por padrão e o CORS libera `http://localhost:5173`.

## 4. Variáveis de ambiente

Modelo em [`.env.example`](.env.example). Segredos nunca entram no Git.

| Variável | Obrigatória | Padrão | Para quê |
|---|---|---|---|
| `DATABASE_URL` | sim | — | String de conexão do Postgres. No Render use a do *pooler* do Supabase |
| `SUPABASE_URL` | sim em produção | — | `https://<projeto>.supabase.co`. Sem ela, as rotas protegidas respondem 503 |
| `CORS_ORIGINS` | sim em produção | `[]` | Origens do front, separadas por vírgula, **sem barra no fim** |
| `DOCS_HABILITADAS` | não | `false` | Liga `/docs`, `/redoc` e `/openapi.json` (só em desenvolvimento) |
| `LIMITE_LEITURA_POR_MINUTO` | não | `120` | Limite de leituras por pessoa |
| `LIMITE_ESCRITA_POR_MINUTO` | não | `30` | Limite de escritas por pessoa |
| `LIMITE_SENSIVEL_POR_MINUTO` | não | `10` | Checkout, abrir chamado e agendar |
| `LIMITE_ANONIMO_POR_MINUTO` | não | `300` | Requisições sem token |
| `LIMITES_ATIVOS` | não | `true` | `false` só em teste |
| `TEST_DATABASE_URL` | só nos testes de banco | — | Postgres **local** com nome terminado em `_teste` |

## 5. Estrutura do projeto

```text
app/
├── main.py              criar_app(): CORS, limite de requisições, cabeçalhos e routers
├── core/                config, db, security (JWT, requer_papel), vigencia, protecoes, erros
├── api/                 router.py (agrega os módulos) e health.py
├── cliente/             loja online: perfil, carrinho, pedidos, chamados, agendamentos
├── chamados/            painel: fila e atendimento de chamados
├── chat/                painel: caixa de conversas e mensagens
├── clientes/            painel: lista e ficha de clientes
├── dashboard/           indicadores do atendimento
├── gerencia/            início do gerente e do admin (vendas, reposição, pendências)
├── painel_estoque/      saldo, movimentações, ajustes, transferências, mínimos
└── gestao/              admin: usuários, catálogo, auditoria, integrações
alembic/versions/        migrations do banco (histórico novo)
supabase/                SQL inicial, seed e scripts para o SQL Editor
scripts/                 contas de teste e dados de exemplo
tests/                   espelha app/ (testes de banco em tests/banco)
docs/                    referência da API e relatório de auditoria
render.yaml              blueprint de deploy no Render
```

Cada módulo segue o mesmo padrão em camadas:

| Arquivo | Responsabilidade |
|---|---|
| `router.py` | só HTTP: recebe, valida o schema, chama o service, devolve |
| `schemas.py` | modelos Pydantic de entrada (`extra="forbid"`) e de saída |
| `service.py` | regras de negócio, escopo de loja e transações |
| `repositorio.py` | SQL parametrizado; nenhum SQL fora dele |
| `erros.py` | subclasses de `ErroDeNegocio`, convertidas em HTTP por um tratador único |

Um módulo novo entra em `app/api/router.py` com uma linha.

## 6. Autenticação e papéis

O front envia `Authorization: Bearer <jwt do Supabase>`. A API valida a assinatura (ES256, chaves em
`<SUPABASE_URL>/auth/v1/.well-known/jwks.json`), a expiração e a audiência.

| Papel | Escopo | O que faz |
|---|---|---|
| `cliente` (sem `papel` no token) | só os próprios dados | compra, acompanha pedidos, abre chamados e agendamentos |
| `atendente` | própria loja + chamados sem loja | fila, chat, clientes |
| `operador_estoque` | própria loja | consulta saldo, registra entrada/saída, **solicita** ajuste e transferência |
| `gerente_loja` | própria loja | tudo da unidade; **aprova ou recusa** ajustes, define estoque mínimo |
| `admin` | rede inteira | tudo, mais usuários, catálogo, auditoria e integrações |

Regras que valem em toda rota:

- O `papel`, a loja e o dono do recurso vêm **do token**, nunca do corpo. Os modelos de entrada recusam campos desconhecidos (422).
- **Vigência:** além do JWT, o `requer_papel` confere no banco (cache de 20 s) se a conta continua ativa e com o mesmo cargo e loja. Desativar ou rebaixar alguém vale em segundos, não em até uma hora.
- Cliente fora do escopo ou recurso de outra loja responde **404**, como se não existisse.

## 7. API

Rotas em `/api/v1/...`, mais `GET /health` e `GET /dashboard/atendimento`. **Toda rota exige token**;
só `GET /health` e `GET /api/v1/cliente/catalogo/estoque` são públicas.

| Grupo | Prefixo | Quem acessa |
|---|---|---|
| Loja do cliente | `/api/v1/cliente` | qualquer pessoa logada (dados do próprio token) |
| Chamados do painel | `/api/v1/painel/atendimentos` | atendente, gerente, admin |
| Chat do atendimento | `/api/v1/painel/chat` | atendente, gerente, admin |
| Clientes do painel | `/api/v1/painel/clientes` | atendente, gerente, admin |
| Estoque do painel | `/api/v1/painel/estoque` | operador, gerente, admin |
| Gerência | `/api/v1/painel/gerencia` | gerente, admin (`/rede`: só admin) |
| Gestão | `/api/v1/painel/gestao` | só admin |
| Dashboard de atendimento | `/dashboard/atendimento` | atendente, gerente, admin |

A lista completa de rotas, com parâmetros e regras de cada uma, está em **[docs/api.md](docs/api.md)**.

**Convenções**

- Erros em português e sem detalhe interno: `401` token inválido, `403` sem permissão, `404` não encontrado, `409` estado não permite a ação (ex.: ajuste já decidido), `422` validação, `429` limite de requisições.
- O `422` devolve `{detail, campos: [{campo, mensagem}]}` sem ecoar o corpo enviado. Erro inesperado vira um `500` genérico; o detalhe só vai para o log.
- Toda listagem é paginada (`limit` padrão 20, máximo 100, e `offset`).
- Dinheiro é `Decimal` (`numeric(12,2)`), nunca `float`. Datas em `timestamptz`; "dia" é o de São Paulo.
- `POST /cliente/pedidos` aceita o header `Idempotency-Key`: repetir a mesma chave devolve o mesmo pedido, sem baixar o estoque duas vezes.

## 8. Banco de dados e migrations

O schema inicial está em `supabase/migrations/` (histórico) e **toda mudança nova usa Alembic**.

```bash
alembic upgrade head                    # aplica tudo
alembic current                         # versão atual do banco
alembic revision -m "descricao"         # cria uma migration nova
alembic downgrade <revisao>             # desfaz até uma revisão
```

Principais tabelas: `loja`, `usuario` (e `tipo_usuario`), `produto`, `variacao_produto`, `estoque`,
`movimentacao_estoque`, `ajuste_estoque`, `transferencia_estoque`, `carrinho`, `pedido`, `item_pedido`,
`pagamento`, `atendimento`, `mensagem`, `avaliacao_atendimento`, `agendamento_cliente`, `auditoria`,
`importacao_lote` e `importacao_registro`. Tabelas de opções
(status, métodos, tipos) são listas controladas pelo banco.

Regras de integridade que o banco garante: chaves estrangeiras, `UNIQUE (id_loja, id_variacao)` no
estoque, `CHECK (quantidade >= 0)`, valores monetários com 2 casas e histórico de movimentação.

**RLS** está ligado e forçado em todas as tabelas do `public`. O front só lê catálogo público e os
dados do próprio usuário ou da própria loja.

**Hook de claims.** No painel do Supabase, ative *Authentication → Hooks → Custom Access Token* com a
função `public.hook_claims_token`. Sem ele, o token da equipe sai sem `papel` e o login do painel é
recusado.

**Triggers de conta** (rodar pelo SQL Editor se a migration avisar que faltou permissão):

- `supabase/cadastro_cliente_trigger.sql` — cadastro pelo site cria o `usuario` sempre como `cliente`.
- `supabase/excluir_conta_trigger.sql` — excluir a conta no Auth desativa o usuário e solta o vínculo.
- `supabase/realtime_chat_policies.sql` — policies do chat ao vivo.

> **Antes de rodar `alembic upgrade head` no banco compartilhado:** avise a equipe, use a conexão
> direta (porta 5432) e confira que `atendente`, `operador_estoque` e `gerente_loja` têm `usuario.id_loja`
> preenchida (sem loja, o token sai sem `loja_id` e a API responde 401).

## 9. Segurança

- **Login em tudo.** O teste `tests/api/test_todas_as_rotas_exigem_login.py` chama todas as rotas sem token e falha se alguma responder diferente de 401.
- **Papel por área.** Cliente logado não entra em nenhuma rota do painel; atendente e operador só entram nas áreas deles.
- **Limite de requisições** por pessoa (hash do token) e por minuto: leitura 120, escrita 30, escrita sensível 10, sem token 300. Excedeu: `429` com `Retry-After`. O contador é em memória, por instância; com várias instâncias, troque por Redis.
- **Cabeçalhos** em toda resposta: `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Cache-Control: no-store`, HSTS e `Referrer-Policy`.
- **Documentação da API fechada** em produção (`/docs`, `/redoc`, `/openapi.json` respondem 404).
- **SQL sempre parametrizado**; o `bandit` analisa o código (seção 10). Nenhum dado de cartão é guardado.
- **Segredos:** a *service role key* nunca vai para o `.env`, o front ou o Git. Só é usada em `scripts/criar_contas.py`, numa variável de ambiente temporária.

O relatório da última auditoria está em [docs/auditoria-2026-10-08.md](docs/auditoria-2026-10-08.md).

## 10. Testes e qualidade

```bash
pytest                        # testes sem banco (os de banco são pulados)
pytest tests/banco -q         # testes contra um Postgres local
ruff check . && ruff format --check .
bandit -r app -q              # análise de segurança
pip-audit -r requirements.txt # vulnerabilidades nas dependências
```

**Testes de banco.** Exigem um PostgreSQL 15+ local, um banco dedicado e a variável:

```text
CREATE DATABASE lorenzi_teste;
TEST_DATABASE_URL=postgresql://postgres:<senha>@127.0.0.1:5432/lorenzi_teste
```

Esses testes **recriam os schemas `public` e `auth`** do banco indicado. Por isso a variável só é aceita
se o host for `localhost`/`127.0.0.1` **e** o nome terminar em `_teste`; qualquer outro destino (como o
Supabase) faz os testes falharem de propósito. Sem a variável, eles são pulados.

Os testes nunca leem o `.env` e rodam com `LIMITES_ATIVOS=false`. Cobrem, entre outros: papel por rota,
escopo de loja, concorrência (aprovar o mesmo ajuste duas vezes dá um 200 e um 409) e transações que
falham no meio sem deixar estado parcial.

## 11. Deploy

**Render** (API). O arquivo [`render.yaml`](render.yaml) descreve o serviço `casa-lorenzi-api`:

- **Build:** `pip install -r requirements.txt`
- **Start:** `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*'`. As migrations rodam antes de subir; se uma falhar, a versão anterior continua no ar.
- **Health check:** `/health`
- **Variáveis** (Environment): `DATABASE_URL`, `SUPABASE_URL` e `CORS_ORIGINS`. O `CORS_ORIGINS` precisa conter a URL exata do front na Vercel, sem barra no fim.
- Deploy automático a cada push na `main`.

> O plano gratuito do Render hiberna a instância; a primeira requisição depois de um tempo parado leva uns 50 s.

**Supabase** guarda o banco, o Auth, o Realtime e o Storage. A ordem da primeira publicação:
1. criar as tabelas (`alembic upgrade head`);
2. ativar o hook de claims;
3. criar as contas da equipe (`scripts/criar_contas.py`);
4. configurar as três variáveis no Render.

## 12. Scripts utilitários

Todos mostram o plano e **não alteram nada** sem `--aplicar`. São só para desenvolvimento.

| Script | O que faz |
|---|---|
| `scripts/criar_contas.py` | cria uma conta para cada papel pelo Supabase Auth e liga à linha de `usuario` |
| `scripts/semear_vendas.py` | lojas, catálogo, clientes fictícios e ~13 meses de pedidos coerentes |
| `scripts/semear_chamados.py` | chamados de exemplo para ver a fila funcionando |
| `scripts/semear_integracao.py` | registros de exemplo para a tela de integrações |

Para `criar_contas.py`, a service role key entra só numa variável do terminal, nunca no `.env`:

```powershell
$env:SUPABASE_SERVICE_ROLE_KEY = '<chave do painel do Supabase>'
python scripts/criar_contas.py --email-base voce@gmail.com --aplicar
Remove-Item Env:SUPABASE_SERVICE_ROLE_KEY
```

As senhas são geradas na hora e aparecem uma única vez na saída; guarde-as em um gerenciador de senhas.

## 13. Como contribuir

- Trabalhe em uma **branch própria** a partir de `intermediaria` (`feat/...`, `fix/...`, `docs/...`).
- `intermediaria` é o branch compartilhado; `main` só recebe o que veio dela, já testado.
- Commits no padrão `<tipo>: <descrição>` com os tipos `feat`, `fix`, `refactor`, `test`, `docs` e `chore`. Exemplo: `feat: aprova ajuste de inventario`.
- Antes de abrir o pull request: `pytest`, `ruff check .` e `bandit -r app -q` limpos.
- **Checklist de um endpoint novo:**
  1. schema de entrada com `extra="forbid"` e `response_model` de saída;
  2. `get_current_user` ou `requer_papel(...)` e checagem do escopo de loja/cliente;
  3. SQL parametrizado, só no repositório;
  4. se mexe em mais de uma tabela ou depende do estado atual: transação com `FOR UPDATE` e checagem do status;
  5. listagem paginada com máximo;
  6. erros em português com o código HTTP certo;
  7. testes do caso feliz, do caso sem permissão e do caso de conflito.
- Mudança de schema é sempre uma migration do Alembic. Nunca altere tabela ou policy só pelo painel do Supabase.

## 14. Problemas comuns

| Sintoma | Causa provável |
|---|---|
| `503` nas rotas protegidas | `SUPABASE_URL` não definida no ambiente |
| `401` com token válido | conta inativa, cargo/loja diferente do token, ou equipe sem `usuario.id_loja` |
| `403` em todas as rotas do painel | hook de claims desligado: o token sai sem `papel` |
| Erro de CORS no navegador (`Disallowed CORS origin`) | `CORS_ORIGINS` sem a URL do front, ou com barra no fim |
| `429 Aguarde...` | limite de requisições por minuto; espere o `Retry-After` |
| `Port scan timeout` no Render | servidor não está em `0.0.0.0:$PORT`; confira o *Start Command* |
| Testes de banco "pulados" | `TEST_DATABASE_URL` não definida |
| `/docs` retorna 404 | é o esperado; use `DOCS_HABILITADAS=true` só em desenvolvimento |
