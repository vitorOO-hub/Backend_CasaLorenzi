# Banco: RLS em todas as tabelas, atendimento e claims — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ligar e forçar RLS em todas as tabelas de `public`, criar as tabelas `atendimento` e `mensagem` com policies por papel/loja e o Custom Access Token Hook que coloca `papel` e `loja_id` no JWT.

**Architecture:** Tudo em migrations SQL do Supabase CLI (fonte única do schema). Segurança em camadas: RLS nega por padrão, policies liberam leitura por papel (claims do JWT) e nenhuma escrita direta em `atendimento`. O FastAPI conecta com usuário que ignora RLS e aplica o escopo no código (plano 2). Tudo é verificado por testes pgTAP (`supabase test db`).

**Tech Stack:** PostgreSQL 15 (Supabase), Supabase CLI via `npx supabase`, pgTAP, Docker Desktop.

**Spec:** `docs/superpowers/specs/2026-10-06-dashboard-atendimento-seguro-design.md` (seção 2). Este é o plano 1 de 3 (banco → backend → frontend). Os outros dois dependem deste.

## Global Constraints

- Identificadores, comentários e mensagens em pt-BR, sem acento em identificadores SQL.
- Todo `id_*` é `uuid` com `default gen_random_uuid()`. Dinheiro não entra neste plano.
- Toda tabela nova de `public` precisa de `enable row level security` **e** `force row level security`; sem policy = sem acesso.
- Policies só `to authenticated`, sempre com `(select auth.uid())` e `(select public.claim_papel())` (subselect, para o planner avaliar uma vez). Nenhuma policy para `anon` em `atendimento`, `mensagem`, `usuario`.
- Nenhuma policy de INSERT/UPDATE/DELETE em `atendimento` (escrita só pelo FastAPI). `mensagem` só aceita INSERT pelo próprio autor.
- Funções `security definer` sempre com `set search_path = ''` e nomes qualificados (`public.`, `auth.`).
- `papel` ∈ {`atendente`, `operador_estoque`, `gerente_loja`, `admin`}. `loja_id` no JWT é texto UUID; obrigatório para `atendente`, `gerente_loja`, `operador_estoque`; ausente para `admin` e cliente.
- Senhas e dados do seed são **fictícios e só locais**. Nunca aplicar `seed*.sql` em produção.
- Nunca rodar `supabase db push`, `supabase link` nem comandos contra o projeto remoto sem o usuário pedir.
- Comandos a partir de `Backend_Casa_Lorenzi/Backend_CasaLorenzi` (Git Bash). A CLI não está instalada: use `npx supabase@latest ...`. Docker Desktop precisa estar aberto.
- Commits no padrão `<tipo>(<escopo>): <descrição>`, terminando com a linha `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Não incluir `CLAUDE.md`, `.gitignore` nem `app/main.py` (alterações do usuário) nos commits deste plano.

## Mapa de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `supabase/seed.sql` | (modificar) tipos `BIGINT` → `UUID`, para o reset funcionar após a migration de uuid |
| `supabase/migrations/20261006000000_rls_todas_as_tabelas.sql` | liga e força RLS em todas as tabelas de `public` |
| `supabase/migrations/20261006000100_atendimento.sql` | enums, tabelas `atendimento` e `mensagem`, índices, triggers, grants |
| `supabase/migrations/20261006000200_claims_e_policies.sql` | `diretor`→`admin`, funções de claim, hook, policies |
| `supabase/seed_atendimento.sql` | dados fictícios locais (lojas, usuários, auth.users, chamados) |
| `supabase/config.toml` | (modificar) seed extra e hook habilitado no ambiente local |
| `supabase/tests/database/001_rls_todas_as_tabelas.test.sql` | garante RLS ligado/forçado e anon sem acesso |
| `supabase/tests/database/002_atendimento_policies.test.sql` | policies de `atendimento`, `mensagem`, `usuario` por papel/loja |
| `supabase/tests/database/003_hook_claims.test.sql` | hook de claims e permissões de execução |
| `README.md` | (modificar) como rodar testes e ativar o hook no painel |

---

### Task 1: Branch, ambiente local e seed compatível com uuid

**Files:**
- Modify: `supabase/seed.sql:3-15`

**Interfaces:**
- Produces: ambiente local do Supabase de pé (`npx supabase start`) e `db reset` funcionando com as 3 migrations existentes.

- [ ] **Step 1: Criar a branch de trabalho**

```bash
git switch -c feat/dashboard-atendimento-seguro
git status --short
```
Expected: branch criada; `app/main.py` aparece como modificado (alteração do usuário, não mexer) e `docs/superpowers/specs/` como não rastreado.

- [ ] **Step 2: Subir o Supabase local**

Run: `npx supabase@latest start`
Expected: baixa as imagens na primeira vez (demora) e termina listando `API URL: http://127.0.0.1:54321` e `DB URL: postgresql://postgres:postgres@127.0.0.1:54322/postgres`. Se falhar com erro de Docker, abra o Docker Desktop e repita.

- [ ] **Step 3: Rodar o reset e ver o seed antigo falhar**

Run: `npx supabase@latest db reset`
Expected: as 3 migrations passam e o `seed.sql` falha com erro de tipo (ex.: `invalid input syntax for type bigint` ou `cannot cast type uuid to bigint`), porque as variáveis do bloco `DO` ainda são `BIGINT` e os ids agora são `uuid`.

- [ ] **Step 4: Corrigir os tipos no seed**

Em `supabase/seed.sql`, nas linhas 3 a 15 (bloco `DECLARE`), troque `BIGINT` por `UUID` em todas as variáveis `v_id_*` (mantenha `INTEGER` nas variáveis `v_quantidade_*` e `v_linhas_atualizadas`). Resultado esperado do bloco:

```sql
    v_id_loja UUID;
    v_id_tipo_cliente UUID;
    v_id_tipo_gerente UUID;
    v_id_cliente UUID;
    v_id_usuario_responsavel UUID;
    v_id_produto UUID;
    v_id_variacao_p UUID;
    v_id_variacao_m UUID;
    v_id_status_pedido_pago UUID;
    v_id_metodo_pagamento_pix UUID;
    v_id_status_pagamento_aprovado UUID;
    v_id_tipo_movimentacao_venda UUID;
    v_id_pedido UUID;
```

- [ ] **Step 5: Rodar o reset de novo**

Run: `npx supabase@latest db reset`
Expected: termina com `Finished supabase db reset on branch ...` sem erro. Se o seed ainda falhar em outra linha, o erro aponta a coluna/tabela: corrija só o que o erro indicar (os ids viraram `uuid`; nenhuma regra de negócio muda) e repita até passar.

- [ ] **Step 6: Commit**

```bash
git add supabase/seed.sql
git commit -m "fix(seed): usa uuid nas variáveis do seed após a migration de ids" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: RLS ligado e forçado em todas as tabelas

**Files:**
- Create: `supabase/tests/database/001_rls_todas_as_tabelas.test.sql`
- Create: `supabase/migrations/20261006000000_rls_todas_as_tabelas.sql`

**Interfaces:**
- Produces: todas as tabelas de `public` com `relrowsecurity` e `relforcerowsecurity` verdadeiros. As policies de `20261005150100_rls_catalogo_publico.sql` passam a valer.

- [ ] **Step 1: Escrever o teste pgTAP (falhando)**

`supabase/tests/database/001_rls_todas_as_tabelas.test.sql`:
```sql
begin;
select plan(4);

select is(
  (select count(*)::int
     from pg_class c
     join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relkind in ('r', 'p') and not c.relrowsecurity),
  0,
  'toda tabela de public tem RLS ligado'
);

select is(
  (select count(*)::int
     from pg_class c
     join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relkind in ('r', 'p') and not c.relforcerowsecurity),
  0,
  'toda tabela de public tem RLS forçado'
);

insert into public.usuario (id_tipo_usuario, nome, email, auth_user_id)
values (
  (select id_tipo_usuario from public.tipo_usuario where codigo = 'cliente'),
  'Fixture RLS',
  'fixture-rls@teste.local',
  '00000000-0000-0000-0000-0000000000a1'
);

set local role anon;
select is((select count(*)::int from public.usuario), 0, 'anon não enxerga nenhum usuario');
reset role;

set local role authenticated;
set local request.jwt.claims to '{"sub":"00000000-0000-0000-0000-0000000000ff","role":"authenticated"}';
select is(
  (select count(*)::int from public.usuario),
  0,
  'usuario logado sem linha própria não enxerga usuarios de outros'
);
reset role;

select * from finish();
rollback;
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `npx supabase@latest test db`
Expected: FAIL nos testes 1 e 2 (há tabelas sem RLS). Os testes 3 e 4 podem passar ou falhar conforme o RLS já ter sido ligado pelo painel; o que importa é ver 1 e 2 falharem. Se 1 e 2 já passarem, o RLS já estava ligado fora das migrations: siga em frente, a migration abaixo é idempotente e registra isso no versionamento.

- [ ] **Step 3: Escrever a migration**

`supabase/migrations/20261006000000_rls_todas_as_tabelas.sql`:
```sql
-- Liga e força o RLS em todas as tabelas de public.
--
-- Motivo: as policies de 20261005150100_rls_catalogo_publico.sql só têm efeito com o RLS ligado, e
-- nenhuma migration o ligava. Sem isso, a chave anon (pública no front) poderia ler tabelas pelo
-- PostgREST. Sem policy, a tabela fica inacessível para anon e authenticated; o FastAPI conecta com
-- um usuário que ignora RLS e aplica papel e loja no código (CLAUDE.md, seção 2).
--
-- Idempotente: pode rodar em um banco que já tenha o RLS ligado pelo painel.
do $$
declare
  tabela record;
begin
  for tabela in
    select c.relname
      from pg_class c
      join pg_namespace n on n.oid = c.relnamespace
     where n.nspname = 'public' and c.relkind in ('r', 'p')
  loop
    execute format('alter table public.%I enable row level security', tabela.relname);
    execute format('alter table public.%I force row level security', tabela.relname);
  end loop;
end $$;
```

- [ ] **Step 4: Aplicar e rodar os testes**

Run: `npx supabase@latest db reset && npx supabase@latest test db`
Expected: `Result: PASS` com os 4 testes de `001_...` passando.

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/20261006000000_rls_todas_as_tabelas.sql supabase/tests/database/001_rls_todas_as_tabelas.test.sql
git commit -m "feat(db): liga e força RLS em todas as tabelas de public" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Tabelas `atendimento` e `mensagem`

**Files:**
- Create: `supabase/migrations/20261006000100_atendimento.sql`

**Interfaces:**
- Consumes: tabelas `loja(id_loja)` e `usuario(id_usuario)` (uuid), `tipo_usuario(codigo)`.
- Produces: enums `status_atendimento`, `prioridade_atendimento`, `canal_atendimento`, `motivo_atendimento`; tabelas `atendimento` e `mensagem` (colunas exatamente como abaixo, o plano 2 as mapeia no SQLAlchemy); RLS ligado e forçado nelas; triggers `trg_atendimento_atualizado_em` e `trg_mensagem_atualiza_atendimento`.

- [ ] **Step 1: Escrever a migration**

`supabase/migrations/20261006000100_atendimento.sql`:
```sql
-- Atendimento (chamados) e mensagens. Escrita em atendimento só pelo FastAPI.

create type public.status_atendimento as enum ('aberto', 'em_andamento', 'resolvido');
create type public.prioridade_atendimento as enum ('alta', 'media', 'baixa');
create type public.canal_atendimento as enum ('whatsapp', 'portal', 'email', 'loja');
create type public.motivo_atendimento as enum ('duvida', 'troca', 'entrega', 'defeito');

create table public.atendimento (
  id_atendimento uuid not null default gen_random_uuid(),
  protocolo text not null,
  id_loja uuid not null,
  id_cliente uuid not null,
  id_atendente uuid,
  assunto text not null,
  canal public.canal_atendimento not null,
  motivo public.motivo_atendimento not null,
  status public.status_atendimento not null default 'aberto',
  prioridade public.prioridade_atendimento not null,
  aberto_em timestamptz not null default now(),
  primeira_resposta_em timestamptz,
  resolvido_em timestamptz,
  ultima_mensagem_em timestamptz,
  atualizado_em timestamptz not null default now(),

  constraint pk_atendimento primary key (id_atendimento),
  constraint uq_atendimento_protocolo unique (protocolo),
  constraint fk_atendimento_loja foreign key (id_loja)
    references public.loja (id_loja) on update cascade on delete restrict,
  constraint fk_atendimento_cliente foreign key (id_cliente)
    references public.usuario (id_usuario) on update cascade on delete restrict,
  constraint fk_atendimento_atendente foreign key (id_atendente)
    references public.usuario (id_usuario) on update cascade on delete restrict,
  constraint chk_atendimento_protocolo check (length(btrim(protocolo)) > 0),
  constraint chk_atendimento_assunto check (length(btrim(assunto)) between 1 and 200),
  constraint chk_atendimento_resolvido check ((status = 'resolvido') = (resolvido_em is not null)),
  constraint chk_atendimento_em_andamento check (status <> 'em_andamento' or id_atendente is not null),
  constraint chk_atendimento_resposta check (primeira_resposta_em is null or primeira_resposta_em >= aberto_em),
  constraint chk_atendimento_resolucao check (resolvido_em is null or resolvido_em >= aberto_em)
);

create table public.mensagem (
  id_mensagem uuid not null default gen_random_uuid(),
  id_atendimento uuid not null,
  id_autor uuid not null,
  texto text not null,
  criada_em timestamptz not null default now(),

  constraint pk_mensagem primary key (id_mensagem),
  constraint fk_mensagem_atendimento foreign key (id_atendimento)
    references public.atendimento (id_atendimento) on update cascade on delete cascade,
  constraint fk_mensagem_autor foreign key (id_autor)
    references public.usuario (id_usuario) on update cascade on delete restrict,
  constraint chk_mensagem_texto check (length(btrim(texto)) between 1 and 4000)
);

-- Índices nas colunas usadas pelas policies e pelos filtros do dashboard.
create index idx_atendimento_loja_status_aberto on public.atendimento (id_loja, status, aberto_em);
create index idx_atendimento_loja_aberto on public.atendimento (id_loja, aberto_em);
create index idx_atendimento_cliente on public.atendimento (id_cliente);
create index idx_atendimento_atendente on public.atendimento (id_atendente) where id_atendente is not null;
create index idx_mensagem_atendimento_criada on public.mensagem (id_atendimento, criada_em);
create index idx_mensagem_autor on public.mensagem (id_autor);

-- atualizado_em automático.
create function public.definir_atualizado_em() returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.atualizado_em := now();
  return new;
end $$;

create trigger trg_atendimento_atualizado_em
  before update on public.atendimento
  for each row execute function public.definir_atualizado_em();

-- Mensagem nova atualiza o chamado: última mensagem e, se a primeira de alguém da equipe, a primeira
-- resposta (base das métricas de tempo de resposta). security definer porque o autor não pode
-- atualizar atendimento diretamente.
create function public.mensagem_atualiza_atendimento() returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  update public.atendimento a
     set ultima_mensagem_em = new.criada_em,
         primeira_resposta_em = coalesce(
           a.primeira_resposta_em,
           case when exists (
             select 1
               from public.usuario u
               join public.tipo_usuario t on t.id_tipo_usuario = u.id_tipo_usuario
              where u.id_usuario = new.id_autor and t.codigo <> 'cliente'
           ) then new.criada_em end
         )
   where a.id_atendimento = new.id_atendimento;
  return new;
end $$;

revoke execute on function public.mensagem_atualiza_atendimento() from public, anon, authenticated;

create trigger trg_mensagem_atualiza_atendimento
  after insert on public.mensagem
  for each row execute function public.mensagem_atualiza_atendimento();

-- RLS: nega por padrão; as policies vêm na migration seguinte.
alter table public.atendimento enable row level security;
alter table public.atendimento force row level security;
alter table public.mensagem enable row level security;
alter table public.mensagem force row level security;

-- Defesa em profundidade nos privilégios (o RLS é a segunda barreira).
revoke all on public.atendimento from anon;
revoke all on public.mensagem from anon;
revoke insert, update, delete on public.atendimento from authenticated;
revoke update, delete on public.mensagem from authenticated;
```

- [ ] **Step 2: Aplicar**

Run: `npx supabase@latest db reset`
Expected: sem erro. Se `type ... already exists`, confirme que o reset limpou o banco (rode de novo).

- [ ] **Step 3: Conferir a estrutura**

Run: `docker exec supabase_db_casa-lorenzi psql -U postgres -c "\d public.atendimento"`
Expected: lista as colunas, as constraints `chk_atendimento_*`, os índices e os triggers. (O nome do container segue `supabase_db_<project_id>`; `project_id` está em `supabase/config.toml`.)

- [ ] **Step 4: Commit**

```bash
git add supabase/migrations/20261006000100_atendimento.sql
git commit -m "feat(db): tabelas de atendimento e mensagem com RLS forçado" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Claims, hook e policies

**Files:**
- Create: `supabase/tests/database/002_atendimento_policies.test.sql`
- Create: `supabase/tests/database/003_hook_claims.test.sql`
- Create: `supabase/migrations/20261006000200_claims_e_policies.sql`

**Interfaces:**
- Consumes: tabelas e triggers da Task 3.
- Produces: `public.claim_papel() returns text`, `public.claim_loja_id() returns uuid`, `public.hook_claims_token(event jsonb) returns jsonb` (executável só por `supabase_auth_admin`); `tipo_usuario.codigo = 'admin'`; policies abaixo.

- [ ] **Step 1: Escrever o teste das policies (falhando)**

`supabase/tests/database/002_atendimento_policies.test.sql`:
```sql
begin;
select plan(20);

-- Fixture (como postgres, que ignora RLS)
insert into public.loja (id_loja, codigo, nome) values
  ('10000000-0000-0000-0000-00000000000a', 'T-LOJA-A', 'Loja A'),
  ('10000000-0000-0000-0000-00000000000b', 'T-LOJA-B', 'Loja B');

insert into public.usuario (id_usuario, id_tipo_usuario, id_loja, auth_user_id, nome, email) values
  ('20000000-0000-0000-0000-000000000001', (select id_tipo_usuario from public.tipo_usuario where codigo = 'cliente'), null, '30000000-0000-0000-0000-000000000001', 'Cliente 1', 'c1@teste.local'),
  ('20000000-0000-0000-0000-000000000002', (select id_tipo_usuario from public.tipo_usuario where codigo = 'cliente'), null, '30000000-0000-0000-0000-000000000002', 'Cliente 2', 'c2@teste.local'),
  ('20000000-0000-0000-0000-000000000011', (select id_tipo_usuario from public.tipo_usuario where codigo = 'atendente'), '10000000-0000-0000-0000-00000000000a', '30000000-0000-0000-0000-000000000011', 'Atendente A', 'ata@teste.local'),
  ('20000000-0000-0000-0000-000000000012', (select id_tipo_usuario from public.tipo_usuario where codigo = 'atendente'), '10000000-0000-0000-0000-00000000000b', '30000000-0000-0000-0000-000000000012', 'Atendente B', 'atb@teste.local'),
  ('20000000-0000-0000-0000-000000000013', (select id_tipo_usuario from public.tipo_usuario where codigo = 'gerente_loja'), '10000000-0000-0000-0000-00000000000a', '30000000-0000-0000-0000-000000000013', 'Gerente A', 'ga@teste.local'),
  ('20000000-0000-0000-0000-000000000014', (select id_tipo_usuario from public.tipo_usuario where codigo = 'admin'), null, '30000000-0000-0000-0000-000000000014', 'Admin', 'admin@teste.local');

insert into public.atendimento (id_atendimento, protocolo, id_loja, id_cliente, assunto, canal, motivo, status, prioridade, resolvido_em) values
  ('40000000-0000-0000-0000-0000000000a1', 'T-A1', '10000000-0000-0000-0000-00000000000a', '20000000-0000-0000-0000-000000000001', 'Defeito na costura', 'whatsapp', 'defeito', 'aberto', 'alta', null),
  ('40000000-0000-0000-0000-0000000000a2', 'T-A2', '10000000-0000-0000-0000-00000000000a', '20000000-0000-0000-0000-000000000001', 'Troca de tamanho', 'portal', 'troca', 'resolvido', 'media', now()),
  ('40000000-0000-0000-0000-0000000000b1', 'T-B1', '10000000-0000-0000-0000-00000000000b', '20000000-0000-0000-0000-000000000002', 'Prazo de entrega', 'email', 'entrega', 'aberto', 'media', null);

-- Atendente da loja A: vê só os chamados da loja A e a própria linha de usuario
set local role authenticated;
set local request.jwt.claims to '{"sub":"30000000-0000-0000-0000-000000000011","role":"authenticated","papel":"atendente","loja_id":"10000000-0000-0000-0000-00000000000a"}';
select is((select count(*)::int from public.atendimento), 2, 'atendente A vê os 2 chamados da loja A');
select is((select count(*)::int from public.atendimento where protocolo = 'T-B1'), 0, 'atendente A não vê chamado da loja B');
select is((select count(*)::int from public.usuario), 1, 'atendente A só enxerga a própria linha de usuario');
select throws_ok($$update public.atendimento set assunto = 'x'$$, '42501', null, 'atendente não altera atendimento direto');
select throws_ok($$insert into public.atendimento (protocolo) values ('x')$$, '42501', null, 'atendente não cria atendimento direto');
select lives_ok(
  $$insert into public.mensagem (id_atendimento, id_autor, texto) values ('40000000-0000-0000-0000-0000000000a1', '20000000-0000-0000-0000-000000000011', 'Olá, já estamos verificando.')$$,
  'atendente A responde chamado da loja A como ele mesmo'
);
select throws_ok(
  $$insert into public.mensagem (id_atendimento, id_autor, texto) values ('40000000-0000-0000-0000-0000000000a1', '20000000-0000-0000-0000-000000000001', 'Falsificando o autor')$$,
  '42501', null, 'atendente não escreve em nome de outro autor'
);
select throws_ok(
  $$insert into public.mensagem (id_atendimento, id_autor, texto) values ('40000000-0000-0000-0000-0000000000a2', '20000000-0000-0000-0000-000000000011', 'Chamado já resolvido')$$,
  '42501', null, 'não é possível responder chamado resolvido'
);
select is((select count(*)::int from public.mensagem), 1, 'atendente A lê a mensagem do chamado que enxerga');
reset role;

select isnt(
  (select primeira_resposta_em from public.atendimento where protocolo = 'T-A1'),
  null::timestamptz,
  'a primeira mensagem da equipe preenche primeira_resposta_em'
);

-- Atendente da loja B
set local role authenticated;
set local request.jwt.claims to '{"sub":"30000000-0000-0000-0000-000000000012","role":"authenticated","papel":"atendente","loja_id":"10000000-0000-0000-0000-00000000000b"}';
select is((select count(*)::int from public.atendimento), 1, 'atendente B vê só o chamado da loja B');
select throws_ok(
  $$insert into public.mensagem (id_atendimento, id_autor, texto) values ('40000000-0000-0000-0000-0000000000a1', '20000000-0000-0000-0000-000000000012', 'Fora da minha loja')$$,
  '42501', null, 'atendente B não responde chamado da loja A'
);
select is((select count(*)::int from public.mensagem), 0, 'atendente B não lê mensagens da loja A');
reset role;

-- Gerente da loja A
set local role authenticated;
set local request.jwt.claims to '{"sub":"30000000-0000-0000-0000-000000000013","role":"authenticated","papel":"gerente_loja","loja_id":"10000000-0000-0000-0000-00000000000a"}';
select is((select count(*)::int from public.atendimento), 2, 'gerente A vê os chamados da loja A');
reset role;

-- Admin
set local role authenticated;
set local request.jwt.claims to '{"sub":"30000000-0000-0000-0000-000000000014","role":"authenticated","papel":"admin"}';
select is((select count(*)::int from public.atendimento), 3, 'admin vê os chamados da rede inteira');
reset role;

-- Clientes
set local role authenticated;
set local request.jwt.claims to '{"sub":"30000000-0000-0000-0000-000000000001","role":"authenticated"}';
select is((select count(*)::int from public.atendimento), 2, 'cliente 1 vê só os próprios chamados');
select is((select count(*)::int from public.mensagem), 1, 'cliente 1 lê as mensagens dos próprios chamados');
reset role;

set local role authenticated;
set local request.jwt.claims to '{"sub":"30000000-0000-0000-0000-000000000002","role":"authenticated"}';
select is((select count(*)::int from public.atendimento), 1, 'cliente 2 vê só o próprio chamado');
select is((select count(*)::int from public.tipo_usuario), 0, 'usuário logado não lê tipo_usuario (sem policy)');
reset role;

-- Anon
set local role anon;
select throws_ok($$select 1 from public.atendimento$$, '42501', null, 'anon não tem acesso a atendimento');
reset role;

select * from finish();
rollback;
```
Contagem: 20 testes (9 do atendente A incluindo o `isnt` fora do bloco → 9 + 1; B: 3; gerente: 1; admin: 1; clientes: 4; anon: 1 = 20). Confira que `plan(20)` bate: se a CLI acusar `planned 20 tests but ran N`, ajuste o número ao total real sem remover testes.

- [ ] **Step 2: Escrever o teste do hook (falhando)**

`supabase/tests/database/003_hook_claims.test.sql`:
```sql
begin;
select plan(9);

insert into public.loja (id_loja, codigo, nome)
values ('10000000-0000-0000-0000-00000000000a', 'T-LOJA-A', 'Loja A');

insert into public.usuario (id_tipo_usuario, id_loja, auth_user_id, nome, email, ativo) values
  ((select id_tipo_usuario from public.tipo_usuario where codigo = 'atendente'), '10000000-0000-0000-0000-00000000000a', '30000000-0000-0000-0000-000000000011', 'Atendente', 'h-ata@teste.local', true),
  ((select id_tipo_usuario from public.tipo_usuario where codigo = 'admin'), null, '30000000-0000-0000-0000-000000000014', 'Admin', 'h-admin@teste.local', true),
  ((select id_tipo_usuario from public.tipo_usuario where codigo = 'cliente'), null, '30000000-0000-0000-0000-000000000001', 'Cliente', 'h-cli@teste.local', true),
  ((select id_tipo_usuario from public.tipo_usuario where codigo = 'gerente_loja'), '10000000-0000-0000-0000-00000000000a', '30000000-0000-0000-0000-000000000099', 'Gerente inativo', 'h-gi@teste.local', false);

create function pg_temp.claims_de(p_auth_id text) returns jsonb
language sql as $$
  select (public.hook_claims_token(jsonb_build_object(
    'user_id', p_auth_id,
    'claims', jsonb_build_object('sub', p_auth_id, 'role', 'authenticated')
  )) -> 'claims')
$$;

select is(pg_temp.claims_de('30000000-0000-0000-0000-000000000011') ->> 'papel', 'atendente', 'atendente recebe papel');
select is(pg_temp.claims_de('30000000-0000-0000-0000-000000000011') ->> 'loja_id', '10000000-0000-0000-0000-00000000000a', 'atendente recebe loja_id');
select is(pg_temp.claims_de('30000000-0000-0000-0000-000000000014') ->> 'papel', 'admin', 'admin recebe papel');
select ok(not (pg_temp.claims_de('30000000-0000-0000-0000-000000000014') ? 'loja_id'), 'admin não recebe loja_id');
select ok(not (pg_temp.claims_de('30000000-0000-0000-0000-000000000001') ? 'papel'), 'cliente não recebe papel');
select ok(not (pg_temp.claims_de('30000000-0000-0000-0000-000000000099') ? 'papel'), 'usuário inativo não recebe papel');
select ok(not (pg_temp.claims_de('30000000-0000-0000-0000-0000000000ee') ? 'papel'), 'usuário desconhecido não recebe papel');
select ok(has_function_privilege('supabase_auth_admin', 'public.hook_claims_token(jsonb)', 'execute'), 'supabase_auth_admin executa o hook');
select ok(
  not has_function_privilege('authenticated', 'public.hook_claims_token(jsonb)', 'execute')
  and not has_function_privilege('anon', 'public.hook_claims_token(jsonb)', 'execute'),
  'authenticated e anon não executam o hook'
);

select * from finish();
rollback;
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `npx supabase@latest test db`
Expected: FAIL em `002_...` e `003_...` (`function public.hook_claims_token(jsonb) does not exist`, `tipo_usuario 'admin'` ausente, sem policies).

- [ ] **Step 4: Escrever a migration de claims e policies**

`supabase/migrations/20261006000200_claims_e_policies.sql`:
```sql
-- Papéis no JWT (Custom Access Token Hook) e policies de leitura por papel e loja.

-- 1. O papel de diretoria passa a se chamar admin (CLAUDE.md, seção 3).
update public.tipo_usuario
   set codigo = 'admin', nome = 'Administrador'
 where codigo = 'diretor';

-- 2. Leitura das claims do JWT dentro das policies.
create function public.claim_papel() returns text
language sql
stable
set search_path = ''
as $$ select nullif(auth.jwt() ->> 'papel', '') $$;

create function public.claim_loja_id() returns uuid
language sql
stable
set search_path = ''
as $$
  select case
    when auth.jwt() ->> 'loja_id' ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    then (auth.jwt() ->> 'loja_id')::uuid
  end
$$;

-- 3. Custom Access Token Hook: grava papel e loja_id no token. Cliente e usuário inativo não recebem
--    papel. Só o Supabase Auth executa. A ativação no painel é manual (ver README).
create function public.hook_claims_token(event jsonb) returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  v_claims jsonb := event -> 'claims';
  v_papel text;
  v_loja uuid;
  v_ativo boolean;
begin
  select t.codigo, u.id_loja, u.ativo
    into v_papel, v_loja, v_ativo
    from public.usuario u
    join public.tipo_usuario t on t.id_tipo_usuario = u.id_tipo_usuario
   where u.auth_user_id = (event ->> 'user_id')::uuid;

  if found and v_ativo and v_papel <> 'cliente' then
    v_claims := v_claims || jsonb_build_object('papel', v_papel);
    if v_loja is not null then
      v_claims := v_claims || jsonb_build_object('loja_id', v_loja::text);
    end if;
  end if;

  return jsonb_set(event, '{claims}', v_claims);
end $$;

grant usage on schema public to supabase_auth_admin;
revoke execute on function public.hook_claims_token(jsonb) from public, anon, authenticated;
grant execute on function public.hook_claims_token(jsonb) to supabase_auth_admin;

-- 4. Policies. Todas só para authenticated; nada para anon.

-- usuario: cada um lê apenas a própria linha (a base das subconsultas das outras policies).
create policy usuario_le_a_propria_linha on public.usuario
  for select to authenticated
  using (auth_user_id = (select auth.uid()));

-- atendimento: cliente lê os próprios; atendente e gerente leem os da própria loja; admin lê todos.
create policy atendimento_cliente_le_os_proprios on public.atendimento
  for select to authenticated
  using (exists (
    select 1 from public.usuario u
     where u.id_usuario = atendimento.id_cliente
       and u.auth_user_id = (select auth.uid())
  ));

create policy atendimento_equipe_le_da_propria_loja on public.atendimento
  for select to authenticated
  using (
    (select public.claim_papel()) in ('atendente', 'gerente_loja')
    and atendimento.id_loja = (select public.claim_loja_id())
  );

create policy atendimento_admin_le_todos on public.atendimento
  for select to authenticated
  using ((select public.claim_papel()) = 'admin');

-- mensagem: lê quem enxerga o atendimento (a subconsulta já passa pelo RLS de atendimento);
-- insere só o próprio autor e só em chamado visível e ainda não resolvido.
create policy mensagem_le_quem_ve_o_atendimento on public.mensagem
  for select to authenticated
  using (exists (
    select 1 from public.atendimento a where a.id_atendimento = mensagem.id_atendimento
  ));

create policy mensagem_insere_o_proprio_autor on public.mensagem
  for insert to authenticated
  with check (
    mensagem.id_autor = (
      select u.id_usuario from public.usuario u where u.auth_user_id = (select auth.uid())
    )
    and exists (
      select 1 from public.atendimento a
       where a.id_atendimento = mensagem.id_atendimento
         and a.status <> 'resolvido'
    )
  );
```

- [ ] **Step 5: Aplicar e rodar todos os testes**

Run: `npx supabase@latest db reset && npx supabase@latest test db`
Expected: `Result: PASS` para `001`, `002` e `003`. Se algum teste de policy falhar com `permission denied` onde se esperava linha, o `GRANT SELECT` padrão de `authenticated` pode ter sido removido: confira com `\dp public.atendimento` que `authenticated` tem `r` (select).

- [ ] **Step 6: Commit**

```bash
git add supabase/migrations/20261006000200_claims_e_policies.sql supabase/tests/database/002_atendimento_policies.test.sql supabase/tests/database/003_hook_claims.test.sql
git commit -m "feat(db): hook de claims e policies de atendimento por papel e loja" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Seed local de atendimento e hook no ambiente local

**Files:**
- Create: `supabase/seed_atendimento.sql`
- Modify: `supabase/config.toml` (linha `sql_paths` e novo bloco `[auth.hook.custom_access_token]`)
- Modify: `README.md`

**Interfaces:**
- Produces: ambiente local com 2 lojas (`LOJA-CENTRO`, `LOJA-PAULISTA`), usuários de equipe e clientes com `auth.users` (senha local `SenhaLocal#2026`), 43 chamados distribuídos nos últimos ~60 dias. O plano 2 usa esses dados nos testes `live`.

- [ ] **Step 1: Escrever o seed**

`supabase/seed_atendimento.sql`:
```sql
-- DADOS FICTÍCIOS, SÓ PARA O AMBIENTE LOCAL (supabase db reset). Nunca aplicar em produção.
-- Senha de todos os usuários locais: SenhaLocal#2026
do $$
declare
  u record;
  v_loja_centro uuid;
  v_loja_paulista uuid;
  v_ate_centro uuid;
  v_ate_paulista uuid;
  v_cliente_1 uuid;
  v_cliente_2 uuid;
  i int;
  v_loja uuid;
  v_atendente uuid;
  v_cliente uuid;
  v_motivo public.motivo_atendimento;
  v_canal public.canal_atendimento;
  v_prioridade public.prioridade_atendimento;
  v_status public.status_atendimento;
  v_aberto timestamptz;
begin
  if exists (select 1 from public.atendimento limit 1) then
    raise notice 'Seed de atendimento já aplicado.';
    return;
  end if;

  insert into public.loja (codigo, nome, cidade, uf)
  values ('LOJA-PAULISTA', 'Casa Lorenzi Paulista', 'Sao Paulo', 'SP')
  on conflict (codigo) do nothing;

  select id_loja into v_loja_centro from public.loja where codigo = 'LOJA-CENTRO';
  select id_loja into v_loja_paulista from public.loja where codigo = 'LOJA-PAULISTA';

  for u in
    select * from (values
      ('40000000-0000-0000-0000-000000000001'::uuid, 'atendente.centro@casalorenzi.local', 'Rafael Nunes', 'atendente', 'LOJA-CENTRO'),
      ('40000000-0000-0000-0000-000000000002'::uuid, 'atendente.paulista@casalorenzi.local', 'Juliana Prado', 'atendente', 'LOJA-PAULISTA'),
      ('40000000-0000-0000-0000-000000000003'::uuid, 'gerente.centro@casalorenzi.local', 'Marina Toledo', 'gerente_loja', 'LOJA-CENTRO'),
      ('40000000-0000-0000-0000-000000000004'::uuid, 'admin@casalorenzi.local', 'Cecilia Lorenzi', 'admin', null),
      ('40000000-0000-0000-0000-000000000005'::uuid, 'helena@casalorenzi.local', 'Helena Vasconcelos', 'cliente', null),
      ('40000000-0000-0000-0000-000000000006'::uuid, 'ricardo@casalorenzi.local', 'Ricardo Menezes', 'cliente', null)
    ) as t(auth_id, email, nome, tipo, loja)
  loop
    insert into auth.users (
      instance_id, id, aud, role, email, encrypted_password, email_confirmed_at,
      raw_app_meta_data, raw_user_meta_data, created_at, updated_at,
      confirmation_token, email_change, email_change_token_new, recovery_token
    ) values (
      '00000000-0000-0000-0000-000000000000', u.auth_id, 'authenticated', 'authenticated', u.email,
      extensions.crypt('SenhaLocal#2026', extensions.gen_salt('bf')), now(),
      '{"provider":"email","providers":["email"]}', '{}', now(), now(), '', '', '', ''
    ) on conflict (id) do nothing;

    insert into auth.identities (id, user_id, provider_id, provider, identity_data, last_sign_in_at, created_at, updated_at)
    values (
      gen_random_uuid(), u.auth_id, u.auth_id::text, 'email',
      jsonb_build_object('sub', u.auth_id::text, 'email', u.email), now(), now(), now()
    ) on conflict do nothing;

    insert into public.usuario (id_tipo_usuario, id_loja, auth_user_id, nome, email)
    values (
      (select id_tipo_usuario from public.tipo_usuario where codigo = u.tipo),
      (select id_loja from public.loja where codigo = u.loja),
      u.auth_id, u.nome, u.email
    )
    on conflict (email) do update
      set auth_user_id = excluded.auth_user_id,
          id_tipo_usuario = excluded.id_tipo_usuario,
          id_loja = excluded.id_loja;
  end loop;

  select id_usuario into v_ate_centro from public.usuario where email = 'atendente.centro@casalorenzi.local';
  select id_usuario into v_ate_paulista from public.usuario where email = 'atendente.paulista@casalorenzi.local';
  select id_usuario into v_cliente_1 from public.usuario where email = 'helena@casalorenzi.local';
  select id_usuario into v_cliente_2 from public.usuario where email = 'ricardo@casalorenzi.local';

  -- 40 chamados antigos, espalhados em ~60 dias, nas duas lojas.
  for i in 1..40 loop
    v_loja := case when i % 2 = 0 then v_loja_centro else v_loja_paulista end;
    v_atendente := case when i % 2 = 0 then v_ate_centro else v_ate_paulista end;
    v_cliente := case when i % 3 = 0 then v_cliente_2 else v_cliente_1 end;
    v_motivo := (array['duvida', 'troca', 'entrega', 'defeito'])[1 + i % 4]::public.motivo_atendimento;
    v_canal := (array['whatsapp', 'portal', 'email', 'loja'])[1 + (i / 4) % 4]::public.canal_atendimento;
    v_prioridade := (case v_motivo when 'defeito' then 'alta' when 'duvida' then 'baixa' else 'media' end)::public.prioridade_atendimento;
    v_status := (case when i % 5 = 0 then 'resolvido' when i % 5 in (3, 4) then 'em_andamento' else 'aberto' end)::public.status_atendimento;
    v_aberto := now() - (i * interval '37 hours');

    insert into public.atendimento (
      protocolo, id_loja, id_cliente, id_atendente, assunto, canal, motivo, status, prioridade,
      aberto_em, primeira_resposta_em, resolvido_em, ultima_mensagem_em
    ) values (
      'AT-' || to_char(v_aberto, 'YYYY') || '-' || lpad(i::text, 4, '0'),
      v_loja, v_cliente,
      case when v_status = 'aberto' then null else v_atendente end,
      'Chamado de teste ' || i, v_canal, v_motivo, v_status, v_prioridade,
      v_aberto,
      case when v_status = 'aberto' then null else v_aberto + (1 + i % 9) * interval '7 minutes' end,
      case when v_status = 'resolvido' then v_aberto + interval '20 hours' end,
      v_aberto + interval '30 minutes'
    );
  end loop;

  -- 3 chamados recentes, sem resposta, para ver os três estados de prazo na fila.
  insert into public.atendimento (protocolo, id_loja, id_cliente, assunto, canal, motivo, status, prioridade, aberto_em)
  values
    ('AT-RECENTE-0001', v_loja_centro, v_cliente_1, 'Defeito recém-aberto (no prazo)', 'whatsapp', 'defeito', 'aberto', 'alta', now() - interval '5 minutes'),
    ('AT-RECENTE-0002', v_loja_centro, v_cliente_2, 'Defeito quase vencendo (em risco)', 'portal', 'defeito', 'aberto', 'alta', now() - interval '26 minutes'),
    ('AT-RECENTE-0003', v_loja_centro, v_cliente_1, 'Entrega vencida (estourado)', 'email', 'entrega', 'aberto', 'media', now() - interval '3 hours');
end $$;
```

- [ ] **Step 2: Registrar o seed e o hook no `config.toml`**

Em `supabase/config.toml`, troque a linha:
```toml
sql_paths = ["./seed.sql"]
```
por:
```toml
sql_paths = ["./seed.sql", "./seed_atendimento.sql"]
```
e acrescente, ao final do arquivo, o bloco:
```toml
# Hook que grava papel e loja_id no JWT. Em produção, ative manualmente no painel
# (Authentication > Hooks > Customize Access Token) apontando para public.hook_claims_token.
[auth.hook.custom_access_token]
enabled = true
uri = "pg-functions://postgres/public/hook_claims_token"
```

- [ ] **Step 3: Aplicar, subir de novo e conferir os dados**

Run: `npx supabase@latest db reset`
Expected: termina sem erro, sem a mensagem de erro do seed.

Run: `docker exec supabase_db_casa-lorenzi psql -U postgres -c "select l.nome, a.status, count(*) from public.atendimento a join public.loja l using (id_loja) group by 1,2 order by 1,2"`
Expected: linhas para as duas lojas com status `aberto`, `em_andamento` e `resolvido` (43 chamados no total).

- [ ] **Step 4: Conferir o token de um usuário local (hook ativo)**

Run:
```bash
curl -s -X POST "http://127.0.0.1:54321/auth/v1/token?grant_type=password" \
  -H "apikey: $(npx supabase@latest status -o env | grep ANON_KEY | cut -d'"' -f2)" \
  -H "Content-Type: application/json" \
  -d '{"email":"atendente.centro@casalorenzi.local","password":"SenhaLocal#2026"}' | head -c 400
```
Expected: JSON com `access_token`. Decodifique o payload (segunda parte do token, base64url) e confira `"papel":"atendente"` e um `loja_id` UUID. Se o login falhar com `converting NULL to string`, as colunas `confirmation_token`/`recovery_token` do seed ficaram nulas: confirme que o `insert into auth.users` passou `''` nelas.

- [ ] **Step 5: Documentar no README**

Em `README.md`, acrescente ao final a seção:

```markdown
## Atendimento, RLS e claims

- Todas as tabelas de `public` têm RLS ligado e forçado (`20261006000000_rls_todas_as_tabelas.sql`).
  **Toda tabela nova precisa de `enable` e `force row level security` na própria migration**; o teste
  `supabase/tests/database/001_rls_todas_as_tabelas.test.sql` falha se alguma ficar de fora.
- Testes do banco: `npx supabase@latest test db` (Docker aberto, banco local de pé).
- `npx supabase@latest db reset` recria o banco local com o seed (`seed.sql` + `seed_atendimento.sql`).
  Usuários locais (senha `SenhaLocal#2026`): `atendente.centro@`, `atendente.paulista@`,
  `gerente.centro@`, `admin@`, `helena@`, `ricardo@` `casalorenzi.local`. Só para ambiente local.
- **Hook de claims em produção (passo manual):** no painel do Supabase, Authentication > Hooks >
  Customize Access Token (JWT) Claims > tipo Postgres Function > `public.hook_claims_token`. Sem
  isso, os tokens da equipe vêm sem `papel` e a API responde 403.
- O papel e a loja só mudam no token depois que ele expira e renova (tokens de 15 a 30 min).
```

- [ ] **Step 6: Rodar tudo e commitar**

Run: `npx supabase@latest db reset && npx supabase@latest test db`
Expected: reset sem erro e `Result: PASS` nos 3 arquivos de teste.

```bash
git add supabase/seed_atendimento.sql supabase/config.toml README.md
git commit -m "feat(db): seed local de atendimento, hook de claims local e docs" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

## Verificação final do plano 1

- [ ] `npx supabase@latest db reset` termina sem erro.
- [ ] `npx supabase@latest test db` → PASS em `001`, `002` e `003`.
- [ ] O token do `atendente.centro@casalorenzi.local` traz `papel` e `loja_id`.
- [ ] Nada foi enviado ao projeto remoto. Para aplicar em produção (pedir confirmação ao usuário antes): `npx supabase@latest link --project-ref <ref>` e `npx supabase@latest db push`, depois ativar o hook no painel.
