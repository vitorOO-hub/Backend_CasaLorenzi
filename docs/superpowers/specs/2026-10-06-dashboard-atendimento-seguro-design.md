# Dashboard de atendimento real e seguro (backend + banco + front) — Design

Data: 2026-10-06
Referências: `CLAUDE.md` (seções 2, 3, 5, 6, 7, 12) e
`docs/superpowers/specs/2026-10-05-supabase-db-auth-design.md` (núcleo de auth, ainda não implementado).

## Objetivo

A home do atendente (`DashboardAtendente`, front) deixa de ler `dados.ts`/`store.ts` e passa a
buscar dados reais na API. Nada sai sem login real, papel e escopo de loja validados no servidor,
e o banco tem RLS ligado em todas as tabelas como segunda barreira.

## Fatos verificados no repositório

- Front: nenhum `fetch`; login é comparação com senhas hardcoded em `sessao.ts`.
- Back: `app/atendimento/` e `app/dashboard/` vazios; `core/security.py` não existe; `/estoques`
  e `/admin` não exigem token; acesso ao banco hoje é `psycopg` síncrono (herança do protótipo
  Flask, commit `528c4eb`), enquanto `CLAUDE.md` e o plano de auth pedem driver assíncrono.
- Banco: nenhuma migration executa `ENABLE ROW LEVEL SECURITY`; as policies de
  `20261005150100_rls_catalogo_publico.sql` só têm efeito se o RLS foi ligado fora das migrations.
  Todos os ids são `uuid`. Clientes e equipe estão na mesma tabela `usuario`
  (`tipo_usuario.codigo`, `auth_user_id`). Não existem `atendimento` nem `mensagem`.
  Não existe o Custom Access Token Hook.

## Decisões

1. **SQLAlchemy 2.0 assíncrono (`create_async_engine`, driver `postgresql+asyncpg`)** em todo
   código novo. O `psycopg` dos módulos `estoque` e `admin` não é tocado (só ganham auth);
   migrá-los é tarefa separada.
2. **Schema e RLS só por migrations SQL do Supabase CLI.** O SQLAlchemy só mapeia (sem
   `create_all`, sem Alembic): uma única fonte de verdade para o schema.
3. **Agregações com SQLAlchemy Core** (`func.count().filter(...)`, `date_trunc`, `generate_series`),
   sempre com parâmetros ligados. Proibido `text()` com f-string.
4. **Atendente pertence a uma loja** (`loja_id` no token, como `CLAUDE.md` §3). Os chamados de uma
   loja chegam só aos atendentes dela; cada atendente escolhe quais assumir da fila
   (`id_atendente` nulo). Atendente não vê estoque nem dados de outras lojas. Só `admin` tem
   `loja_id` nulo e vê a rede, podendo filtrar por loja.
5. Código do papel `diretor` é renomeado para `admin` na migration.
6. Portal do cliente e demais telas do painel continuam com dados fictícios; só a equipe interna
   usa o login real agora.

## 1. Backend: núcleo de auth (`app/core`)

Conforme o spec de 2026-10-05, com estas diferenças:

- `core/security.py`: JWT ES256 via JWKS em cache (rebusca no máximo 1x/60 s, com lock),
  `aud=authenticated`, `iss=<SUPABASE_URL>/auth/v1`, `exp/sub/aud/iss` obrigatórios, token ≤ 8 KB,
  rejeita `alg` ≠ ES256, anônimo e claims incoerentes (`loja_id` obrigatório para `atendente`,
  `gerente_loja` e `operador_estoque`; proibido para `admin` e cliente). `get_current_user`,
  `requer_papel(*papeis)`.
  Enum `Papel`: `atendente`, `operador_estoque`, `gerente_loja`, `admin`. `loja_id` é `UUID`.
- `core/db.py` (novo, SQLAlchemy): um `AsyncEngine` criado no `lifespan`, `async_sessionmaker`
  com `expire_on_commit=False`, dependência `get_sessao` (uma transação por requisição,
  commit/rollback automático).
  - Pooler Supabase em modo transação: `connect_args={"statement_cache_size": 0,
    "prepared_statement_cache_size": 0, "prepared_statement_name_func": <nome único>}`.
  - `pool_size` pequeno, `pool_pre_ping=True`, timeout de conexão e de comando.
  - `SET LOCAL statement_timeout` no início de cada transação (parâmetro de startup não é
    aceito pelo pooler).
  - `DATABASE_URL` continua `postgresql://...`; o `+asyncpg` é acrescentado em código.
- `core/limite_requisicoes.py`: slowapi, limite global por IP e dependência
  `limite_por_usuario(limite, escopo=...)` (chave = usuário já validado). 429 com `Retry-After`.
- `/estoques` e `/admin` passam a depender de `requer_papel` (estoque: operador_estoque,
  gerente_loja, admin; admin: admin). Rotas de estoque checam a loja do token.
- CORS só com `CORS_ORIGINS`; `/docs` e `/openapi.json` desligados quando `AMBIENTE=producao`.
- `/health` sem auth.

## 2. Banco (migrations novas em `supabase/migrations/`)

1. `..._rls_todas_as_tabelas.sql`: `ENABLE` e `FORCE ROW LEVEL SECURITY` em **todas** as tabelas de
   `public` (inclusive as de opções). Sem policy = sem acesso. Reaplica `revoke` de privilégios
   em `anon`/`authenticated` nas tabelas novas.
2. `..._atendimento.sql`:
   - Enums: `status_atendimento` (aberto, em_andamento, resolvido), `prioridade_atendimento`
     (alta, media, baixa), `canal_atendimento` (whatsapp, portal, email, loja),
     `motivo_atendimento` (duvida, troca, entrega, defeito).
   - `atendimento`: `id_atendimento uuid`, `protocolo` UNIQUE, `id_loja` FK, `id_cliente` FK
     `usuario`, `id_atendente` FK `usuario` nulo (nulo = na fila), `assunto` (1–200), `canal`,
     `motivo`, `status`, `prioridade`, `aberto_em`, `primeira_resposta_em`, `resolvido_em`,
     `ultima_mensagem_em`, `atualizado_em`. CHECKs: assunto não vazio; `resolvido_em` só com status
     resolvido; `primeira_resposta_em >= aberto_em`; `resolvido_em >= aberto_em`.
   - `mensagem`: `id_mensagem uuid`, `id_atendimento` FK, `id_autor` FK `usuario`, `texto` (1–4000),
     `criada_em`.
   - Índices: `(id_loja, status, aberto_em)`, `(id_loja, aberto_em)`, `(id_cliente)`,
     `(id_atendente)`, `(id_atendimento, criada_em)` nas colunas usadas pelas policies e filtros.
3. `..._claims_e_policies.sql`:
   - Renomeia `tipo_usuario.codigo` `diretor` → `admin`.
   - **Custom Access Token Hook** (`public.hook_claims_token(event jsonb) returns jsonb`,
     `SECURITY DEFINER`, `search_path` fixo, `EXECUTE` só para `supabase_auth_admin`): lê `usuario`
     por `auth_user_id` e grava `papel` e `loja_id`; cliente não recebe `papel`; usuário inativo
     recebe token sem papel. **Ativação no painel do Supabase é passo manual.**
   - Policies (todas com `(select auth.uid())`, `to authenticated`; nenhuma para `anon`):
     - `usuario`: SELECT só da própria linha (`auth_user_id = auth.uid()`).
     - `atendimento` SELECT: cliente vê os próprios; `atendente` e `gerente_loja` veem os da própria
       loja (`atendimento.id_loja = claim loja_id`); `admin` vê todos. Sem INSERT/UPDATE/DELETE:
       escrita só pelo FastAPI (inclusive assumir o chamado).
     - `mensagem` SELECT: quem vê o atendimento. INSERT: autor = usuário logado, atendimento visível
       para ele e não resolvido.
   - O FastAPI conecta com usuário que ignora RLS; as policies protegem o caminho PostgREST/Realtime.
4. `supabase/seed.sql`: dados de atendimento fictícios só para ambiente local.

## 3. Backend: módulo `atendimento`

Camadas `router.py` → `service.py` → `repositorio.py` (SQLAlchemy), schemas Pydantic v2 com
`extra="forbid"` e `response_model`. Modelos ORM mínimos (`Atendimento`, `Mensagem`, referências a
`Usuario`/`Loja`) em `atendimento/modelos.py`.

- `GET /api/v1/dashboard/atendimento` — query: `inicio`, `fim` (data/hora, `fim > inicio`, janela
  máxima 400 dias), `granularidade` (`dia|semana|mes`), `id_loja` (opcional), `canal`, `motivo`
  (enums). Resposta: `atual` e `anterior` (mesma duração, imediatamente antes) com `total`,
  `resolvidos`, `taxa_resolucao`, `resposta_media_horas`; `serie_volume` (buckets com zeros via
  `generate_series`); `por_motivo`; `resposta_por_canal`.
- `GET /api/v1/atendimentos/fila` — não resolvidos, `limit` (padrão 20, máx. 100) e `offset`,
  filtros `id_loja`, `canal`, `motivo`. Ordem: prazo estourado, em risco, prioridade, mais antigo.
  Prazos: alta 30 min, média 2 h, baixa 4 h. Resposta inclui `total_aberto`, `sem_resposta` e
  `urgentes` e itens com `id_atendimento`, `protocolo`, `assunto`, `cliente_nome`, `loja_nome`,
  `canal`, `prioridade`, `status`, `aberto_em`, `na_fila` (sem atendente) e `meu` (atribuído ao
  usuário logado). Nunca devolve e-mail, telefone ou documento do cliente.
- Escopo: papéis `atendente`, `gerente_loja`, `admin`. Para `atendente` e `gerente_loja`, o
  `id_loja` efetivo é sempre o do token (sem `id_loja` na query = o do token); `id_loja` diferente
  do token → 403. `admin`: filtro livre ou rede inteira.
- O repositório já modela "assumir" (`UPDATE ... WHERE id_atendente IS NULL`, 409 se perdeu a
  corrida), mas o endpoint `POST /atendimentos/{id}/assumir` **fica fora desta entrega** (a home só
  lista a fila); entra na fatia seguinte, junto com a tela do chamado.
- Rate limit: leitura 120/min por usuário. Erros em português (401/403/422/429), 500 genérico sem
  detalhe do banco; erro de conexão → 503.

## 4. Frontend

- Dependência `@supabase/supabase-js`. `lib/supabase.ts` cria o cliente com `VITE_SUPABASE_URL` e
  `VITE_SUPABASE_ANON_KEY` (chave pública; a service role nunca entra no front) e storage em
  `sessionStorage`.
- `sessao.ts` / `Entrar.tsx`: login interno real (`signInWithPassword`); papel e loja lidos do JWT
  (claims); remove `credenciaisInternas`. Mapa de papéis: `atendente→atendente`,
  `operador_estoque→operador`, `gerente_loja→gerente`, `admin→administrador`. Login de cliente
  segue demo. Mensagem de erro de login genérica.
- `lib/api.ts`: `fetch` com `Authorization: Bearer <access_token>`, URL de `VITE_API_URL` (HTTPS
  obrigatório fora de localhost), timeout com `AbortController`, valida o formato da resposta antes
  de usar, trata 401 (renova uma vez; se falhar, sai), 403, 429 (`Retry-After`) e rede.
  Sem logar token.
- `hooks/useDashboardAtendimento.ts`: busca resumo e fila, cancela a requisição ao desmontar ou
  trocar filtro, estados `carregando | erro | pronto`.
- `Atendente.tsx`: troca `todosOsAtendimentos`/`chamados` pelos dados da API; mantém a
  apresentação e os componentes de gráfico. Atendente e gerente não têm seletor de loja (o
  cabeçalho mostra a loja do token); só `admin` vê o seletor "Loja", e ele não usa mais `lojas` mock. Estados de carregando, erro com "tentar de novo" e fila vazia.
- Hardening: nenhum `dangerouslySetInnerHTML`; `vercel.json` com CSP (`default-src 'self'`,
  `connect-src` só API e Supabase), `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`,
  `Referrer-Policy`, `Permissions-Policy`; `.env.example` sem valores reais.

## Testes

- Back `unit`: claims → usuário, matriz de `requer_papel`, escopo de loja, janela de datas,
  compilação das consultas (SQL parametrizado, sem literais do usuário).
- Back `seguranca`: token expirado, `aud/iss` errados, `alg=none`, HS256 com chave pública,
  payload adulterado, `kid` desconhecido, claims incoerentes; gerente tentando outra loja = 403;
  `extra` desconhecido (inclusive `papel`, `id_loja` no corpo) = 422; `/estoques` e `/admin` sem
  token = 401.
- Back `api`: contrato dos dois endpoints com `dependency_overrides`; 429; CORS permitido e negado.
- Banco: script SQL de verificação (opt-in contra Supabase local): RLS ligado em todas as tabelas de
  `public`; `anon` sem acesso a `atendimento`, `mensagem` e `usuario`; cliente só vê os próprios
  chamados; atendente de outra loja não vê nada; hook devolve claims corretas.
- Front: Vitest para `api.ts` (401, 403, 429, timeout, formato inválido) e para o mapeamento de
  papéis; `tsc -b`, `oxlint`.
- Lint/segurança: `ruff`, `bandit`, `pip-audit`, `npm audit`.

## Fora do escopo

Migrar `estoque`/`admin` para SQLAlchemy; telas além da home do atendente; portal do cliente real;
escrita de chamados e mensagens pelo FastAPI; Redis; ativação do hook no painel (passo manual,
documentado no README).

## Riscos e pendências

- Hook de claims precisa ser ativado manualmente no Supabase; sem ele, todo token de equipe vem sem
  `papel` e a API responde 403.
- Se o RLS já estava ligado pelo painel, a migration 1 é idempotente (apenas `FORCE`).
- O protótipo mostra o atendente como "todas as casas" (`equipe.atendente` sem `lojaId`); o front
  passa a ler a loja do JWT e o seletor de loja só aparece para `admin`.
- Atendente sem `loja_id` no cadastro (`usuario.id_loja` nulo) recebe token incoerente e a API
  responde 401. O seed local e o cadastro de usuário (`POST /usuarios`, fora do escopo) precisam
  preencher a loja.
