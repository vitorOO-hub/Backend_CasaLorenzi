# Núcleo de auth, RLS e policies sobre a base da `intermediaria` — Design

Data: 2026-10-06
Branch: `feat/rls-policies-auth` (criada a partir de `origin/intermediaria`, commit `9fd55b2`)
Referências: `CLAUDE.md` (seções 2, 3, 5, 7, 12) e `docs/superpowers/specs/2026-10-05-supabase-db-auth-design.md`.

Este spec **substitui** a proposta de migrar o projeto para SQLAlchemy assíncrono com modelos ORM e
de apagar `supabase/migrations`. Essa migração já foi feita de outro jeito pelo outro integrante da
equipe, na `intermediaria`, e **não será alterada**. O spec e o plano de dashboard de atendimento
do commit `66ea715` (branch `rotas-admin`) ficam desatualizados: assumiam um schema de atendimento
que não é o real.

## Objetivo

Colocar uma barreira de segurança real sobre o que já existe, sem reescrever nem quebrar o trabalho
do outro integrante (inclusive a tela do cliente):

1. Validar o JWT do Supabase e oferecer papel e escopo de loja ao código Python.
2. Proteger o banco com RLS, privilégios mínimos e policies por papel e por loja, versionados em
   Alembic.
3. Provar o comportamento com testes contra um Postgres real.

## Fatos verificados (banco remoto e repositório, em 2026-10-06)

- **Alembic já funciona** na `intermediaria`: `alembic/env.py` síncrono, `target_metadata = None`
  (sem modelos), cadeia `20261005000000` (baseline **vazio**; o schema inicial vem dos 3 SQLs de
  `supabase/migrations/`) → `20261006213000` (tabelas de atendimento, escritas com `op.execute`).
  O banco remoto está nesse `head`.
- **SQLAlchemy Core síncrono** com `create_engine` e driver `psycopg` (`app/core/db.py`). Os módulos
  `estoque`, `admin`, `compras`, `movimentacoes` e `atendimento` usam esse padrão.
- **Nenhuma rota tem autenticação.** `requer_papel`, `get_current_user` e JWT não existem no código.
- **A identidade vem do corpo da requisição** em atendimento (`id_cliente`, `id_usuario_remetente`,
  `id_usuario_responsavel`) e em compras e movimentações (`id_cliente`, `id_usuario_responsavel`).
- **O banco tem 23 tabelas em `public`**, todas com RLS ligado (por event trigger `ensure_rls` do
  painel) e `FORCE` desligado. **Só 5 policies existem**, todas de leitura (`loja`, `produto`,
  `variacao_produto`, `metodo_pagamento`, `status_pedido`). As demais tabelas ficam trancadas para
  `anon` e `authenticated`.
- **O hook de claims não existe.** Não há FK de tabelas de `public` para `auth.users`:
  `usuario.auth_user_id` é uma coluna `uuid` sem FK.
- **O usuário da API (`postgres`) tem `BYPASSRLS`.** RLS e `FORCE` não afetam a API; só protegem o
  acesso direto do front ao Supabase (PostgREST e Realtime).
- **Modelo de usuário:** uma tabela `usuario` (cliente e equipe) com `id_tipo_usuario`, `id_loja`,
  `auth_user_id`, `ativo`. Códigos em `tipo_usuario`: `cliente`, `operador_estoque`, `atendente`,
  `gerente_loja`, `diretor`. O teste `tests/admin/test_router.py` usa `"papel": "diretor"`.
- **`atendimento` não tem `id_loja`.** Os status reais são `aberto`, `em_andamento`,
  `aguardando_cliente`, `resolvido`, `encerrado`, `cancelado`; as prioridades, `baixa`, `media`,
  `alta`, `urgente`.
- O banco remoto é **compartilhado** com o outro integrante. Os dados atuais são de desenvolvimento
  (2 usuários, 1 loja, 1 produto, 1 pedido, nenhum atendimento).

## Decisões

1. **Convenções do outro integrante são o padrão do projeto:** SQLAlchemy Core síncrono, revisões
   Alembic escritas à mão, `supabase/migrations` mantido como histórico inicial. Nada disso é
   reescrito aqui. Divergência registrada com o `CLAUDE.md` §12.4 (pede acesso assíncrono): as
   rotas `def` rodam em threadpool e funcionam; decisão de mudar fica para outro momento.
2. **Código novo entra em arquivos novos.** Nenhum arquivo de módulo do outro integrante é editado.
   Os únicos arquivos existentes tocados são `app/api/router.py`, `app/core/config.py`,
   `app/main.py` (se a flag exigir validação no startup), `.env.example`, `requirements*.txt` e
   `README.md`.
3. **A trava de autenticação é controlada por flag** (`AUTENTICACAO_OBRIGATORIA`, padrão `false`),
   para a tela do cliente continuar funcionando até o front enviar o JWT.
4. **`diretor` vira `admin` apenas no token**, dentro do hook. Nenhum dado nem código existente muda.
5. **`atendimento.id_loja` é adicionada nullable**, com trigger que a preenche a partir do pedido,
   porque o `POST /atendimentos` atual não envia loja.
6. **Escrita só pela API**, com duas exceções diretas do front previstas no `CLAUDE.md` §6:
   `INSERT` em `mensagem` e em `avaliacao_atendimento`.

## 1. Núcleo de auth (`app/core`)

Arquivos novos: `app/core/security.py` e `app/core/papeis.py`.

- **Validação do JWT:** assinatura, `exp`, `aud="authenticated"`, `iss="<SUPABASE_URL>/auth/v1"`,
  `sub` obrigatório, tamanho máximo do token, rejeição de `alg` inesperado e de `none`. Antes de
  implementar, confirmar no projeto Supabase se as chaves são assimétricas (JWKS, ES256) ou
  HS256 com segredo (`CLAUDE.md` §3). Em JWKS, as chaves ficam em cache com lock e rebusca limitada.
  Busca de JWKS com `httpx` síncrono e timeout.
- **`Papel`:** `atendente`, `operador_estoque`, `gerente_loja`, `admin`.
- **`UsuarioAtual`:** `id_auth: UUID`, `papel: Papel | None` (cliente não tem papel),
  `id_loja: UUID | None`.
- **Claims incoerentes dão 401:** `atendente`, `gerente_loja` e `operador_estoque` exigem `loja_id`;
  `admin` e cliente não podem ter `loja_id`; papel desconhecido é recusado.
- **Dependências (síncronas):** `get_current_user`, `requer_papel(*papeis)` e um helper de escopo de
  loja. Papel ou loja insuficiente dá 403; token ausente ou inválido dá 401. Mensagens em português,
  sem vazar detalhe interno.
- **`Settings`:** novos campos `autenticacao_obrigatoria: bool = False`. `supabase_url` já existe e
  passa a ser obrigatório quando a flag está ligada (falha no startup com mensagem clara).

### Trava por flag em `app/api/router.py`

`include_router(..., dependencies=[...])` por módulo. Com a flag desligada a dependência não bloqueia
nada. Com a flag ligada:

| Módulo | Exige |
|---|---|
| `/admin` | `admin` |
| `/estoques`, `/movimentacoes` | `operador_estoque`, `gerente_loja` ou `admin` |
| `/atendimentos`, `/compras` | qualquer usuário autenticado e ativo |
| `/health` | nada |

**Limite assumido:** a trava só barra acesso anônimo e papel inadequado. Ela **não impede** que um
cliente logado leia ou altere dados de outro cliente em `/atendimentos` e `/compras`, nem que uma
loja mexa na outra em `/estoques`, porque isso exige filtro por dono ou por loja **dentro dos
handlers**. Essas correções ficam como lista para decisão conjunta (ver "Fora do escopo").

## 2. Banco: uma revisão Alembic nova

Arquivo `alembic/versions/20261007000000_rls_policies_claims.py`, `down_revision = "20261006213000"`,
escrito à mão com `op.execute`, com `downgrade` completo. Idempotente onde possível.

1. **RLS explícito:** `ENABLE` e `FORCE ROW LEVEL SECURITY` em todas as tabelas de `public`
   (exceto `alembic_version`). A revisão deixa de depender do event trigger `ensure_rls` do painel.
2. **Privilégios mínimos:** `REVOKE ALL` em todas as tabelas de `public` para `anon` e
   `authenticated`, e `GRANT` só do necessário: `SELECT` onde há policy e `INSERT` em `mensagem` e
   `avaliacao_atendimento`. `ALTER DEFAULT PRIVILEGES` para tabelas futuras criadas por `postgres`
   nascerem sem grant.
3. **Funções auxiliares** (`SECURITY DEFINER`, `search_path` fixo, `EXECUTE` revogado de `public`):
   - `app_usuario_id()`: `usuario.id_usuario` a partir de `auth.uid()` (a chave é
     `usuario.auth_user_id`).
   - `app_papel()` e `app_loja_id()`: lidos das claims do JWT.
   - `app_pode_ver_atendimento(uuid)`: regra única reaproveitada pelas policies.
4. **Hook de claims** `public.hook_claims_token(event jsonb) returns jsonb`: lê `usuario` e
   `tipo_usuario` por `auth_user_id`; grava `papel` (traduzindo `diretor` → `admin`) e `loja_id`.
   Cliente não recebe `papel`; usuário inativo ou inexistente sai sem papel. `EXECUTE` só para
   `supabase_auth_admin`. **A ativação em Authentication → Hooks no painel do Supabase é passo
   manual**, documentado no README. Sem ela, todo token de equipe vem sem papel.
5. **`atendimento.id_loja`:** coluna `uuid` nullable, FK para `loja`, índice, e trigger
   `BEFORE INSERT` que preenche `id_loja` com `pedido.id_loja` quando `id_pedido` está presente e
   `id_loja` é nulo.
6. **Policies** (`to authenticated`, `(select auth.uid())`, índice nas colunas filtradas; nenhuma
   policy nova para `anon`):

| Tabela | SELECT | INSERT |
|---|---|---|
| `usuario` | só a própria linha | — |
| `atendimento` | cliente: os próprios; `atendente` e `gerente_loja`: os da própria loja; `admin`: todos | — |
| `atendimento_item` | quem vê o atendimento | — |
| `mensagem` | quem vê o atendimento | autor = usuário logado, atendimento visível e em status aberto, em andamento ou aguardando cliente |
| `avaliacao_atendimento` | dono do atendimento, equipe da loja, `admin` | só o dono, e só com status `resolvido` ou `encerrado` |
| `pedido`, `item_pedido`, `pagamento` | cliente: os próprios; equipe: os da própria loja; `admin`: todos | — |
| `estoque`, `movimentacao_estoque` | `operador_estoque` e `gerente_loja` da própria loja; `admin` | — |
| tabelas de opções (`status_*`, `tipo_*`, `canal_*`, `categoria_*`, `prioridade_*`, `metodo_pagamento`) | usuários logados | — |

   Sem policy de `UPDATE` ou `DELETE` em lugar nenhum: escrita só pela API.
7. **Aplicação no banco remoto:** a revisão afeta o banco compartilhado com o outro integrante.
   Ela é validada primeiro no Postgres de teste. **`alembic upgrade head` no remoto só roda depois
   de autorização explícita**, e o comando e o efeito esperado vão no plano.

## 3. Testes

- **Postgres real em container** (exige Docker Desktop aberto). Um script de bootstrap cria os
  papéis `anon`, `authenticated` e `supabase_auth_admin` e o schema `auth` com `uid()` e `jwt()`
  lendo `request.jwt.claims`, como o Supabase faz.
- **Fixture de sessão:** aplica `supabase/migrations/*.sql` em ordem (o baseline do Alembic é vazio e
  depende deles) e depois roda `alembic upgrade head`. Cada teste roda em transação com rollback.
- **Testes de RLS** com `SET LOCAL ROLE authenticated` e claims injetadas: cliente só vê os próprios
  chamados; atendente de outra loja não vê nada; `anon` não lê `atendimento`, `mensagem` nem
  `usuario`; mensagem só do próprio autor e em chamado aberto; avaliação só do dono e só depois de
  resolvido; nenhuma escrita direta fora das duas exceções; o hook devolve as claims corretas
  (inclusive `diretor` → `admin`, cliente sem papel, inativo sem papel).
- **Teste do trigger** de `id_loja` e do `downgrade` da revisão.
- **Testes de auth, sem banco:** token expirado, `aud` e `iss` errados, `alg=none`, confusão
  HS256 × chave pública, payload adulterado, `kid` desconhecido, claims incoerentes, matriz de
  `requer_papel`, token ausente (401), e a flag ligada e desligada (com a flag desligada as rotas
  atuais continuam respondendo como hoje).
- **Opt-in:** testes de banco usam `TEST_DATABASE_URL` e marcador `banco`. Sem a variável, são
  pulados com mensagem clara. Os testes mockados existentes não mudam.
- **Lint e segurança:** `ruff`, `bandit`, `pip-audit`.

## Fora do escopo (specs próprios)

- **Correções dentro dos handlers do outro integrante:** tirar `id_cliente` e `id_usuario_*` do corpo
  e usar o token; "assumir" atômico (`UPDATE ... WHERE id_usuario_responsavel IS NULL`, 409 na
  corrida); validação de transição de status; checagem de dono na avaliação; filtro por loja em
  estoque e movimentações. Mudam o contrato com o front e quebram a tela do cliente até ele
  enviar o JWT, portanto dependem de acordo entre os dois.
- **Dashboard de atendimento** (endpoints e front) e fila de chamados.
- **`prepare_threshold=None` no `create_engine`:** psycopg 3 prepara statements automaticamente e
  isso não funciona com o pooler Supavisor em modo transação; só aparece em produção, sob carga.
  Registrado para o outro integrante decidir.
- Rate limit (`slowapi`), paginação em rotas antigas, auditoria, importação da Vulto.
- Migrar para acesso assíncrono.

## Riscos e pendências

- **Hook de claims inativo = API devolve 403 para toda a equipe** quando a flag estiver ligada.
  Ativar no painel antes de ligar a flag.
- **Revisão no banco compartilhado:** `REVOKE` e `FORCE` mudam o acesso direto via PostgREST. A API
  não é afetada (papel `postgres`, `BYPASSRLS`). O outro integrante precisa saber antes do upgrade.
- **Daemon do Docker parado** na máquina de desenvolvimento no momento da escrita: os testes de
  banco exigem abri-lo.
- **Chamados sem pedido** ficam com `id_loja` nulo e só aparecem para o dono e para `admin` até o
  cadastro passar a informar a loja.
- **Escolha do algoritmo do JWT** (JWKS × HS256) ainda não verificada no projeto Supabase; é a
  primeira tarefa do plano.
