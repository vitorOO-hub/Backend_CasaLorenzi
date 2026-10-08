# Auditoria ponta a ponta — Casa Lorenzi (2026-10-08)

Somente leitura: nenhum código, migration ou dado foi alterado. Consultas ao banco remoto foram feitas em
transação `READ ONLY`. A suíte de testes e a matriz de papéis rodaram no **Postgres local de teste**
(nunca no remoto). Nenhum segredo foi impresso.

**Versões auditadas:** backend `intermediaria` @ `48a6b2e` · frontend `develop` @ `a5ed856` ·
banco remoto com `alembic_version = 20261008100000` (todas as migrations aplicadas).

Convenção de status: **CONFIRMADO** (li o código e/ou reproduzi/consultei o dado), **PROVÁVEL** (evidência
forte, sem reprodução completa), **NÃO VERIFICADO** (com o motivo).

---

## 1. Resumo executivo

**Risco geral: ALTO.** A parte nova (`/api/v1/painel/*`, `/api/v1/cliente/*`, `/dashboard`) está bem
construída: JWT ES256 por JWKS, papel e loja só de claims assinadas, escopo de loja nos services, RLS
habilitada e forçada em todas as tabelas, nenhuma escrita direta do front além de `mensagem` e
`avaliacao_atendimento`. O risco alto vem do **código legado ainda montado na API** e de lacunas de
operação (ciclo de vida do token, rate limit).

### Os 5 achados mais graves

| # | ID | Sev. | Resumo |
|---|----|------|--------|
| 1 | F1-01 | **CRÍTICO** | `/compras/*` e `/atendimentos/*` aceitam **qualquer token válido, inclusive de cliente**, sem papel nem escopo: um cliente logado lê todos os pedidos/atendimentos da rede, altera status de pedido e pagamento, cancela pedidos e posta mensagem com remetente arbitrário. O front não usa nenhuma dessas rotas. |
| 2 | F1-02 | **CRÍTICO (condicional)** | Com `AUTENTICACAO_OBRIGATORIA=false` o legado inteiro, incluindo `/admin/*` (CRUD de usuários, lojas, produtos), fica **sem login**. Hoje o padrão fecha quando há `SUPABASE_URL`, mas um `false` esquecido no ambiente abre tudo. O valor em produção não foi verificado. |
| 3 | F1-03 | **ALTO** | Legado `/estoques/*` e `/transferencias-estoque/*`: o operador de **qualquer** loja lista e movimenta o estoque de **outra** loja (só confere o papel, não a loja) e faz ajuste de inventário sem passar pela aprovação do gerente. |
| 4 | F2-01 / F2-02 | **MÉDIO→ALTO** | Token já emitido continua autorizado até expirar (~1 h) depois de desativar o usuário; e equipe inativa/sem vínculo vira "cliente autenticado", que passa em F1-01. O backend não consulta `ativo`. |
| 5 | F6-01 | **ALTO** | `slowapi` está no `requirements.txt`, mas **não há nenhum Limiter no código**: nenhuma rota tem rate limit (checkout, chat, chamados, cadastro via API). |

Também relevantes: `/docs`/`/openapi.json` públicos (F1-10/F6-05), estoque por loja público e sem
paginação (F1-04), e divergências de integridade nos dados (seção 5).

### O que está bem (evidência)
- **Autenticação nas 140 rotas**: matriz de 140 rotas × 10 atores (sem token, token adulterado, expirado,
  assinado por outra chave, papel inexistente, cliente, atendente, operador, gerente, admin) — **nenhuma
  rota respondeu 2xx para token ausente/adulterado/expirado/de outra chave** (exceto as públicas),
  e **papel inexistente nunca passou** (sempre 401/403). Arquivo: `auditoria/matriz.py` (scratchpad).
- **RLS**: todas as 35 tabelas de `public` com RLS ligada; 34 com FORCE (a exceção é `alembic_version`,
  sem grants). Nenhuma view. Nenhum `INSERT/UPDATE/DELETE` para `anon`/`authenticated` além de
  `mensagem` e `avaliacao_atendimento`.
- **Contas**: nenhum `auth.users` sem linha em `usuario`; nenhum `auth_user_id` duplicado ou órfão;
  e-mails idênticos entre Auth e `usuario`; nenhum cargo de loja ativo sem loja.
- **Segredos**: nenhum segredo versionado nos dois repositórios; o front só recebe `VITE_*` (anon key).
- **Dependências do front**: `npm audit --omit=dev` → 0 vulnerabilidades.
- **Testes**: backend 1225 passam; frontend 424 passam; `tsc` limpo.

---

## 2. Tabela de achados

Severidade: C=crítico · A=alto · M=médio · B=baixo. Esforço: P/M/G.

### Frente 1 — Rotas e contrato

| ID | Sev. | Descrição | Evidência | Impacto | Correção | Esf. | Status |
|----|------|-----------|-----------|---------|----------|------|--------|
| F1-01 | C | `/compras/*` e `/atendimentos/*` com `trava()` sem papéis: aceita qualquer token, inclusive cliente. Services não recebem o usuário. | `app/api/router.py:30-31`; `app/core/security.py:119-132` (com `permitidos` vazio nunca nega). **Matriz**: com token de **cliente**, `GET /compras/pedidos`=200, `GET /atendimentos`=200, `POST /compras/pedidos`=422, `PATCH /compras/pedidos/{id}/status`=422, `POST /atendimentos/{id}/mensagens`=422 (passou da autorização; só o corpo vazio barrou). | IDOR/escalada: cliente vê dados de todos, muda status de pedido/pagamento, cancela, cria pedido para outro cliente, posta mensagem com `id_usuario_remetente` arbitrário. | Desmontar `compras_router` e `atendimento_router` (front não usa) ou `trava(Papel.ADMIN)` + escopo. | P | CONFIRMADO |
| F1-02 | C* | `trava()` não faz nada com a flag `false`; abre `/admin/*`, `/compras`, `/atendimentos`, GETs de `/estoques`, etc. | `app/core/security.py:129`; `app/core/config.py:20-24,47-53`; teste do subagente: `GET /admin/usuarios` passou da autenticação com a flag `False`. | Variável de ambiente errada expõe a administração inteira sem login. | Remover o modo aberto de `/admin`; recusar `false` quando houver `SUPABASE_URL`; apagar o legado. | P | CONFIRMADO (código); valor em produção NÃO VERIFICADO (variável só existe no Render) |
| F1-03 | A | Legado `/estoques/{id}/entrada|saida|ajuste` e `/transferencias-estoque`: exige `operador_estoque` mas não confere a loja do registro. | `app/estoque/router.py:20-60` (só `usuario.id_auth` é passado; sem `id_loja`). **Matriz**: operador recebe 200 em `GET /estoques`, `/movimentacoes-estoque`, `/transferencias-estoque` (listas de todas as lojas); gerente e admin recebem 403 nessas rotas. | Operador da loja A mexe no estoque da loja B; ajuste direto pula a aprovação do gerente. | Remover (o front usa `/painel/estoque/*`) ou aplicar `garantir_escopo_de_loja`. | P/M | CONFIRMADO |
| F1-04 | A* | `GET /api/v1/cliente/catalogo/estoque` é pública, sem limite nem paginação, e devolve saldo exato por loja. | `app/cliente/router.py:44-52`; matriz: 200 para todos os atores. | Dado operacional exposto a anônimos; custo/DoS sem rate limit. | Devolver só disponibilidade (faixa/booleano) a anônimos; cache. | P | CONFIRMADO (se é problema depende da regra de negócio) |
| F1-05 | M | `src/api/backend.ts` (~30 chamadas) aponta para rotas que não existem (`/api/v1/movimentacoes`, `/pedidos`, `/usuarios`…). Código morto. | `src/api/backend.ts:46-128`; nenhum import fora do arquivo. | Se alguém passar a usar, tudo vira 404; sugere contrato antigo. | Apagar `backend.ts` e `direto.ts` (e limpar `index.ts`). | P | CONFIRMADO |
| F1-06 | M | 422 do Pydantic não tem handler: `msg` em inglês e `input` ecoado; `lib/api.ts` cai em "Não foi possível carregar os dados." | teste: `PATCH /api/v1/painel/gestao/catalogo/{id}` com `{}` → "Value error, Informe o que mudar"; `src/lib/api.ts:70-81`. | Erro de formulário genérico/enganoso; eco do corpo. | Handler global 422 → pt-BR, sem `input`. | M | CONFIRMADO |
| F1-07 | M | `http.ts` (portal) mostra o `detail` cru do servidor em 401/404 ("Token invalido ou ausente", "Not Found"). | `src/api/erros.ts:66-78`; `app/core/erros_auth.py:13-17`. | Texto técnico para o cliente quando a sessão expira. | Usar `mensagemPadrao` nesses casos; unificar os 2 clientes HTTP. | P | CONFIRMADO |
| F1-08 | M | Redirecionamento ao login em 401 só em 4 pontos (`useChamados`, `useDashboardAtendimento`, `useDashboardGerente`, `chatAoVivo`). Estoque, gestão, clientes, rede, equipe e portal ficam com a tela de erro. | grep em `src/hooks/*`. | Sessão que não renova deixa o usuário preso. | Tratar 401 num único ponto (cliente HTTP/provider). | M | CONFIRMADO |
| F1-09 | B | Listas com teto fixo e sem paginação no front: pedidos e chamados do cliente (20 primeiros), catálogo (100), mínimos (200). | `src/lib/comprasClienteApi.ts:136`, `chamadosClienteApi.ts:139`, `gestaoApi.ts`; backend `le=100/200`. | Acima do teto o dado some sem aviso. | "Carregar mais" usando `total`. | M | CONFIRMADO (pedidos/chamados); PROVÁVEL nos demais |
| F1-10 | B | `/docs`, `/redoc`, `/openapi.json` públicos. | `app/main.py:18-19`; `tests/api/test_todas_as_rotas_exigem_login.py:24-27` libera de propósito. | Enumeração de toda a API (inclui o legado). | Desligar em produção. | P | CONFIRMADO |
| F1-11 | B | Convenções mistas: `/dashboard/atendimento` fora de `/api/v1`; dinheiro ora `string` (cliente) ora `number` (painel). | `app/api/router.py:33`. | Nenhum erro hoje; validador futuro com `numero()` quebra. | Padronizar. | P | CONFIRMADO |
| F1-12 | B | O front lê `produto`/`variacao_produto`/`usuario` direto do Supabase (depende só de RLS). | `src/lib/catalogoApi.ts:162`, `src/lib/sessao.ts:90`. | — (RLS verificada na frente 3: ok). | — | — | CONFIRMADO (RLS adequada) |

\* condicional / depende de decisão de negócio.

### Frente 2 — Autenticação, sessão e JWT

| ID | Sev. | Descrição | Evidência | Impacto | Correção | Esf. | Status |
|----|------|-----------|-----------|---------|----------|------|--------|
| F2-01 | M | Papel e loja vêm só das claims; o token não traz `ativo` e `requer_papel`/`trava` não consultam o banco. | `app/core/security.py:49-63,105-108`; `README.md:245-247` admite; `supabase/config.toml:34` `jwt_expiry=3600`. | Após `ativo=false` o access token segue válido até ~1 h; o refresh só perde o papel no próximo refresh (vira "cliente"). | Ao desativar, chamar a Admin API do Supabase (signOut global/ban); conferir `ativo` com cache curto; `jwt_expiry` menor. | M | CONFIRMADO (código); `jwt_expiry` remoto NÃO VERIFICADO |
| F2-02 | M | Equipe inativa, sem linha em `usuario` ou com tipo inativo sai do hook **sem papel** e é aceita como cliente autenticado. | Hook `…000200` l.34-49; `security.py:54`; combina com F1-01. | Ex-funcionário/órfão acessa `/atendimentos` e `/compras`. | Resolver o usuário no banco nos handlers legados (ou remover o legado, F1-01). | M | CONFIRMADO |
| F2-03 | M | `auth_user_id` nulo/divergente: equipe vira cliente sem aviso no servidor; o aviso do front só dispara se conseguir ler o perfil. | Hook l.44; `src/lib/sessao.ts:143-151`. | Conta de equipe "muda" para cliente em silêncio. | Alerta/log server-side quando `sub` não tem linha em `usuario`. | P | CONFIRMADO |
| F2-04 | M | Trigger de cadastro de cliente em `auth.users` é criado num bloco que engole `insufficient_privilege`; sem FK `usuario.auth_user_id → auth.users`. | migration `20261007200000` l.142-157; consulta: FK = 0. **No banco remoto o trigger existe** (`trg_criar_cliente_no_cadastro`, habilitado). | Em ambiente sem permissão, `signUp` cria Auth sem `usuario`. Excluir no Auth deixa `usuario` órfão e prende o e-mail (`uq_usuario_email`). | Trigger `AFTER DELETE` em `auth.users` (ou FK `ON DELETE SET NULL`); checar o trigger em cada ambiente. | M | CONFIRMADO |
| F2-05 | M | Cadastro: oráculo de e-mail (erro × sucesso falso) e confirmação de e-mail dependente da config remota; validação só nos CHECKs. | trigger l.93-101,107; `src/api/auth.ts`. Cargo é fixo `cliente` e nenhum código lê `user_metadata` (seguro). | Enumeração de e-mails de funcionários sem login; conta criada com e-mail de terceiro se a confirmação estiver desligada. | Exigir confirmação de e-mail; captcha; resposta idêntica. | P/M | CONFIRMADO (código); config remota NÃO VERIFICADA (3 contas não confirmadas hoje) |
| F2-06 | B | Hook de claims correto (`diretor`→`admin`, cliente sem papel, `ativo` filtrado, `SECURITY DEFINER` com `search_path` fixo, `EXECUTE` só para `supabase_auth_admin`), mas a ativação é manual no painel. | `…000200` l.27-63; ACL no banco: `postgres, service_role, supabase_auth_admin`. Os tokens reais de admin/gerente carregam `papel` (as telas do painel funcionam). | Sem a ativação, todo token de equipe sai sem papel (403). | Documentar/verificar na implantação. | P | CONFIRMADO (código e ACL); ativação inferida pelo uso, não lida do painel |
| F2-07 | B | `autenticacao_obrigatoria` nasce `None` e liga sozinha com `SUPABASE_URL` (spec dizia `false`). `false` ainda desliga a trava. | `app/core/config.py:26,47-53`. | Mais seguro que a spec, mas ver F1-02. | Recusar `false` em produção. | P | CONFIRMADO |
| F2-08 | B | Dois clientes HTTP paralelos com políticas de erro diferentes. | `src/api/http.ts` e `src/lib/api.ts`. | Divergência de política de sessão. | Unificar. | M | CONFIRMADO |
| F2-09 | B | `getSession()` não valida o token no servidor; a UI mostra o papel de um token possivelmente revogado até a 1ª chamada. | `src/api/supabase.ts:24`, `sessao.ts:187`. | UX; atrasa a detecção de desativação. | `getUser()` no boot do painel. | P | CONFIRMADO |
| F2-10 | B | `sair()` não espera o `signOut` do Supabase. | `src/lib/sessao.ts:226-231`. | Se a rede falhar, o refresh token continua válido no servidor. | Aguardar/repetir. | P | PROVÁVEL |
| F2-11/12 | B | Resíduos de mock na sessão: `CLIENTE_DEMO_ID` ("c1") e `equipe[papel].lojaId`. | `sessao.ts:21-26,120,224,251-254`. | Só UX; risco de alguém filtrar por `lojaDoPapel`. | Remover. | P | CONFIRMADO |

**JWT no backend — verificação positiva (CONFIRMADO):** só `ES256` (header exigido e `algorithms=["ES256"]`),
`none`/HS256 rejeitados; checa assinatura, `exp`, `aud="authenticated"`, `iss`, `sub`; tamanho máx. 8192;
chave por JWKS (cache por `kid`, lock, rebusca limitada a 1/60 s); sem segredo HS256; papel/loja de claims
top-level que só o hook escreve; claims incoerentes (papel de loja sem loja, admin com loja, `role` ≠
`authenticated`, `is_anonymous`) → 401. Matriz: token adulterado, expirado e assinado por outra chave → 401.

### Frente 3 — RLS (consulta direta ao banco remoto, somente leitura)

| ID | Sev. | Descrição | Evidência | Status |
|----|------|-----------|-----------|--------|
| F3-01 | B | Funções `trigger` com `EXECUTE` herdado por `PUBLIC` (`definir_protocolo_atendimento`, `preencher_id_loja_atendimento`, `validar_endereco_usuario`, `validar_movimentacao_estoque`) e `rls_auto_enable` (`SECURITY DEFINER`, `search_path=pg_catalog`). | `pg_proc` + `has_function_privilege`. Funções de trigger não são chamáveis por RPC; `rls_auto_enable` é do Supabase. | CONFIRMADO (listagem); explorabilidade = hipótese de baixo risco |
| F3-02 | B | `alembic_version` com RLS ligada, sem FORCE e sem grants. | `pg_class`. Inofensiva (sem acesso para os roles do front). | CONFIRMADO |
| F3-03 | M | **Storage sem bucket nem policies no banco**: `storage.buckets` e `storage.objects` vazios. Anexos de chamado dependem de bucket/policies criados à mão (ou não existem). | consulta em `storage.buckets`/`pg_policies(schema=storage)`: 0 linhas; nenhuma migration cria bucket (`grep` no repo). | CONFIRMADO (o banco não tem); config feita só no painel NÃO VERIFICÁVEL por SQL |
| F3-04 | B | Conexão da API usa o role `postgres` com `BYPASSRLS=true` (não superuser): toda checagem de escopo está no Python. | `pg_roles`. É o desenho documentado; por isso F1-01/F1-03 importam. | CONFIRMADO |

**Resultado por tabela (35 em `public`):** RLS ligada em todas; `FORCE` em 34. Sem policy e sem grants
(fechadas ao front, só a API): `agenda_horario`, `agendamento_cliente`, `auditoria`, `carrinho`,
`chamado_leitura`, `importacao_lote`, `importacao_registro`, `alembic_version`. `anon` só lê `loja`
(ativas), `produto` (ativos) e `variacao_produto` (ativas de produto ativo). `authenticated` só tem
`SELECT` (+ `INSERT` em `mensagem` e `avaliacao_atendimento`). **Não há `UPDATE`/`DELETE` para nenhum role
do front** (negado por falta de grant).

**Policies de leitura (resumo):** `usuario`: só a própria linha (`auth_user_id = auth.uid()`);
`pedido`: dono ou equipe da loja; `estoque`/`movimentacao_estoque`: operador/gerente da loja ou admin;
`ajuste_estoque`: gerente da loja ou o operador que pediu; `transferencia_estoque`: operador/gerente de
origem ou destino; `mensagem`/`atendimento`/`chamado_anexo`/…: `app_pode_ver_atendimento` (dono, ou
atendente/gerente da loja, ou admin). `mensagem` INSERT: só o próprio autor, **só cliente** (`app_papel()
IS NULL`), em chamado em andamento.

**Helpers:** `app_usuario_id`, `app_pode_ver_atendimento`, `app_pode_avaliar_atendimento`,
`app_atendimento_aceita_mensagem` são `SECURITY DEFINER` com `search_path = public, pg_temp`; todos usam
`(SELECT auth.uid())`/`(SELECT auth.jwt())` em subselect; `EXECUTE` só para `authenticated` (não `anon`).
`app_papel_na_loja` exige usuário ativo e compara a loja do claim. Sem caminho de escalada encontrado.
`realtime.messages`: policies de canal privado `chamado:<uuid>` amarradas a `app_pode_ver_atendimento`.

### Frente 4 — Contas e vínculo auth ↔ usuario (consultas SELECT no banco remoto)

| ID | Sev. | Achado | Evidência | Status |
|----|------|--------|-----------|--------|
| F4-01 | M | Sem FK entre `usuario.auth_user_id` e `auth.users` (0 FKs). Hoje 0 órfãos e 0 duplicados. | consulta | CONFIRMADO |
| F4-02 | B | Equipe ativa **sem login** (sem `auth_user_id`): gerente_loja 3, operador_estoque 2 (cadastros de exemplo). Aparecem na Gestão como "Ainda sem login". | consulta | CONFIRMADO |
| F4-03 | B | 37 clientes ativos sem vínculo com o Auth (cadastros de exemplo) e 39 de 42 clientes ativos sem endereço completo (anteriores à regra). Permitido pelo trigger (linhas antigas). | consulta | CONFIRMADO |
| F4-04 | B | 3 contas em `auth.users` sem e-mail confirmado. | consulta | CONFIRMADO |
| — | ok | 0 `auth.users` sem `usuario`; 0 `auth_user_id` órfão/duplicado; 0 e-mails divergentes; 0 e-mails duplicados (unique `uq_usuario_email`); 0 cargos de loja ativos sem loja; 0 `diretor`/`cliente` com loja; 0 `id_loja` apontando para loja inativa. | consulta | CONFIRMADO |

**Rotas administrativas:** `/api/v1/painel/gestao/usuarios` (admin) impede o admin de desativar/rebaixar a
si mesmo e de deixar a rede sem administrador (testes de banco cobrem). O legado `/admin/usuarios`
(`PATCH` livre, incluindo `id_tipo_usuario` e `auth_user_id`) é só `trava(ADMIN)` — ver F1-02 (aberto se a
flag for `false`). Desativar não revoga token já emitido (F2-01).

### Frente 5 — Integridade dos dados

| ID | Sev. | Achado | Evidência | Status |
|----|------|--------|-----------|--------|
| F5-01 | M | **8 de 185** linhas de `estoque` têm saldo menor que o último `quantidade_posterior` gravado (diferença de 1–2 un.). Nos 8 casos o último movimento é uma `entrada` e `estoque.atualizado_em` é idêntico (`2026-10-07 18:23:33.503674`): atualização em lote sem movimentação correspondente. | consulta: batem 177, divergem 8. | CONFIRMADO (divergência); origem PROVÁVEL = script de semente/ajuste manual, não rota da API |
| F5-02 | B | 334 quebras de encadeamento (`anterior` ≠ `posterior` da movimentação anterior) em 3.579 pares: 114 são empate de horário (ordenação por `criada_em` com id UUID aleatório) e 220 têm horário distinto. | consulta | CONFIRMADO; causa PROVÁVEL = movimentações semeadas com `criada_em` retroativo e saldos calculados fora da ordem cronológica. **Não** reproduzido por teste de concorrência (os de `painel_estoque_escrita`/`transferencias_minimos` passam) |
| F5-03 | M | Checkout não grava o frete em coluna: insere `valor_total=0`, `observacao` com o frete e depois recalcula; `valor_frete` fica 0. 1 de 1.990 pedidos tem `valor_total` (508,00) ≠ itens (459,00) + `valor_frete` (0,00): R$ 49,00 de frete só no texto da `observacao`. | `app/cliente/repositorio.py:1162-1173`; pedido `PD-20261007-4EDC6695`. | CONFIRMADO |
| F5-04 | ok | Saldo nunca negativo (0 linhas; `CHECK quantidade >= 0`). `posterior = anterior + sinal × quantidade` em 100% das 3.763 movimentações. 0 pedidos sem itens. Enums batem entre banco, Pydantic e TypeScript: papéis `atendente / operador_estoque / gerente_loja / admin` (`diretor`↔`admin`); tipos de movimentação (8) e grupos; status de pedido e de atendimento. | consultas + `app/core/papeis.py`, `src/api/tipos.ts` | CONFIRMADO |
| F5-05 | ok | Conferências cruzadas das telas × SQL independente (no banco remoto): faturamento da rede 365 dias = soma mês a mês; faturamento/pedidos/peças do painel = SQL (R$ 482.497,00 / 465 / 844 em 90 dias); estoque (unidades) e chamados abertos = SQL; saldo por loja/peça = tabela `estoque`; movimentações por tipo/loja/período = SQL; **peças**: 15 produtos (loja, saldo, início do admin e catálogo) e 63 SKUs. | scripts em `scratchpad/` | CONFIRMADO |
| F5-06 | B | `supabase/migrations/` (3 arquivos SQL) e `alembic/versions/` (21 revisões) coexistem; o banco de teste aplica os SQL e depois o Alembic. Todas as 21 revisões têm `downgrade`; cadeia linear e cabeça única verificadas por teste (`test_cadeia_alembic`). Banco remoto na cabeça `20261008100000`. | `ls`, `get_heads()` | CONFIRMADO |
| F5-07 | B | Concorrência de estoque: há testes com threads em `test_painel_estoque_escrita`, `test_transferencias_minimos`, `test_chamados_repositorio` (travam a linha com `FOR UPDATE`). **Não há teste de concorrência para o legado** `app/estoque` (que também usa `FOR UPDATE` na entrada). | `grep` em `tests/`; `app/estoque/repositorio.py:69` | CONFIRMADO |

### Frente 6 — Segurança geral e configuração

| ID | Sev. | Achado | Evidência | Status |
|----|------|--------|-----------|--------|
| F6-01 | A | **Sem rate limit**: `slowapi>=0.1.9` no `requirements.txt` mas nenhum `Limiter` em `app/`. | `requirements.txt:27`; `grep -rn "slowapi|Limiter" app/` → vazio (confirmado por mim). | CONFIRMADO |
| F6-02 | M | Bucket do Storage e policies de `storage.objects` fora do repositório e ausentes do banco (ver F3-03). | `grep` em alembic/supabase; consulta. | CONFIRMADO (ausentes no repo/banco) |
| F6-03 | B | `anexarArquivo` (front) faria `INSERT` em `chamado_anexo`, mas o banco só dá `SELECT`; a função **não é chamada por nenhuma tela** (código morto). A tela "Novo chamado" tem campo de fotos, mas em modo API **não envia os anexos**. | `src/api/direto.ts:243-257`; `grep` de uso = 0; `NovoChamado.tsx:125-131` (payload sem anexos); grants no banco. | CONFIRMADO (a funcionalidade de foto está incompleta; risco de segurança só se alguém "consertar" com grant amplo) |
| F6-04 | M | Validação de upload só no cliente (MIME declarado e 5 MB); caminho com `randomUUID` e nome saneado. | `direto.ts:245-246`. | PROVÁVEL (sem bucket não há como impor limite no servidor) |
| F6-05 | M | `/docs`, `/redoc`, `/openapi.json` públicos (= F1-10). | `app/main.py:19`. | CONFIRMADO |
| F6-06 | M | Sem handler genérico de `Exception`/`RequestValidationError`/`IntegrityError` e sem headers de segurança (CSP, `X-Frame-Options`, HSTS, `nosniff`); sem `vercel.json`. | `app/core/erros.py`; ausência de middleware. Não há `debug=True`. | PROVÁVEL (não vi as respostas reais em produção) |
| F6-07 | B | Sem limite global de tamanho de corpo. | sem middleware; todas as rotas exigem login. | PROVÁVEL |
| F6-08 | B | SQL por f-string (8 ocorrências do Bandit, todas Medium/Low): nenhuma injeção; valores sempre por parâmetro, identificadores de whitelist ou constantes. Frágil: `montar_insert/update` aceitam nome de coluna de `model_dump()`. | `app/core/repositorio.py:73,89` etc. | CONFIRMADO (sem injeção) |
| F6-09 | B | CORS correto: lista explícita, métodos/headers enumerados, sem credenciais e sem `*`. | `app/main.py:21-27`. Valor de produção NÃO VERIFICADO. | CONFIRMADO (código) |
| F6-10 | B | Sessão do Supabase em `localStorage` (padrão do supabase-js); sem vetor de XSS encontrado (`dangerouslySetInnerHTML`/`innerHTML`/`eval`: 0). | `src/api/supabase.ts:17`. | CONFIRMADO |
| F6-11 | B | `?voltar=` do login protegido (aceita só caminho relativo; recusa `//`, `\`, `/esquema:`). | `src/lib/destino.ts:8-14`. | CONFIRMADO |
| F6-12 | B | Sem `target="_blank"`/`window.open`; URL assinada de anexo de 300 s. | grep em `src/`. | CONFIRMADO |
| F6-13 | — | Sem segredos versionados; `.gitignore` cobre `.env*`; `git ls-files` só tem `.env.example`; front só com `VITE_*` (sem `service_role`). | git. Varredura de valores no histórico de `.py/.sql` não feita (recomendado `gitleaks`). | CONFIRMADO (arquivos); histórico NÃO VERIFICADO |
| F6-14 | M | `pip-audit` bloqueado pela política de aplicativos do Windows; `requirements.txt` sem lock (só `>=`). `npm audit` (prod) = 0. | execução. | NÃO VERIFICADO (backend) / CONFIRMADO (front) |

### Frente 7 — Testes e execução real

| Item | Resultado |
|------|-----------|
| Backend `pytest` | **1225 passaram, 0 falharam, 0 ignorados** (execução limpa em 115 s). Numa primeira execução, feita junto de outras consultas pesadas, houve **1 falha não identificada** (o nome se perdeu) que **não se repetiu** — suspeita de sensibilidade a carga/tempo; **NÃO REPRODUZIDO**. |
| Frontend `vitest` | **424 passaram** (39 arquivos), sem falhas. |
| `tsc` | limpo (`tsc -b` e `--noEmit`). |
| Lint front | `oxlint` sem erros; avisos de `react-refresh` e `preserve-manual-memoization` (cosméticos). Não há ESLint configurado. |
| Backend `ruff`/`bandit` | `ruff` limpo nos módulos do projeto auditados na sessão; `bandit`: 8 avisos B608 Medium/Low (F6-08). Erros de estilo pré-existentes em arquivos de colegas (`app/admin/*`, `app/cliente/schemas.py`…). |
| Smoke test (TestClient) | **140 rotas × 10 atores** — ver seção 3. |

**Áreas críticas com cobertura boa:** RLS e policies por papel (`test_rls_*`, `test_policies_*`), JWT/JWKS
(`tests/core/test_security_jwt.py`, `test_jwks.py`), matriz de papel (`test_painel_so_para_equipe`,
`test_todas_as_rotas_exigem_login`), concorrência no painel de estoque novo. **Sem teste:** legado
(`/compras`, `/atendimentos`, `/admin`, `/estoques`) quanto a **papel/escopo** (o teste só exige
"estar logado" — por isso F1-01 passa), concorrência no estoque legado, ciclo de vida do token
(desativação), rate limit, Storage/anexos.

---

## 3. Matriz papel × recurso (execução real, 140 rotas × 10 atores)

Executada contra o app real (`TestClient`) com tokens ES256 de teste e **um usuário real por papel no banco
de teste local** (`sub` do token = `auth_user_id`; atendente/operador/gerente na mesma loja; admin sem
loja; cliente com endereço). Corpos de escrita vazios: `422` = "autorizado, corpo inválido, nada gravado";
`200/404` = autorizado. Script: `auditoria/matriz.py` (scratchpad); saída: `auditoria/matriz_saida2.txt`.

**Atores sem papel válido** (sem token, token adulterado, expirado, assinado por outra chave, `papel`
inexistente): **nenhuma rota respondeu 2xx** (fora as públicas `/health`, `/api/v1/cliente/catalogo/estoque`,
`/docs`…). **Papel inexistente nunca passou** (sempre 401/403).

| Recurso | Cliente | Atendente | Operador | Gerente | Admin | Esperado? |
|---------|:------:|:--------:|:-------:|:------:|:----:|-----------|
| `/api/v1/cliente/*` (carrinho, pedidos, chamados, perfil, agendamentos, lojas) | **200/404/422** | 403 | 403 | 403 | 403 | ✅ só o cliente (corpo é validado antes do 403 do service: com corpo válido staff recebe 403) |
| `GET /api/v1/cliente/catalogo/estoque` | 200 | 200 | 200 | 200 | 200 | ✅ público por desenho (ver F1-04) |
| `/api/v1/painel/{atendimentos,chat,clientes}`, `/dashboard/atendimento*` | 403 | **200/404** | 403 | **200/404** | **200/404** | ✅ |
| `POST` mensagem em `/painel/{atendimentos,chat}` | 403 | 422 | 403 | 422 | 422 | ✅ |
| `/api/v1/painel/estoque/{opcoes,saldo,movimentacoes,ajustes,transferencias}` (leitura) | 403 | 403 | **200** | **200** | **200** | ✅ |
| `POST` em `/painel/estoque/{movimentacoes,ajustes,transferencias,reposicoes}` | 403 | 403 | 422 | 422 | 422 | ✅ |
| `POST /painel/estoque/ajustes/{id}/aprovar|recusar`, `GET|PUT /minimos` | 403 | 403 | **403** | 404/422/200 | 404/422/200 | ✅ só gerente e admin |
| `/painel/estoque/transferencias/{id}/{aceitar,receber,recusar}` | 403 | 403 | 404* | 404* | 404* | ✅ (404 = id inexistente, já autorizado) |
| `/api/v1/painel/gerencia/{dashboard,lojas,pendencias,reposicao}` | 403 | 403 | 403 | **200** | **200** | ✅ |
| `/api/v1/painel/gerencia/rede`, `/api/v1/painel/gestao/*` | 403 | 403 | 403 | 403 | **200/404/422** | ✅ só admin |
| `/admin/*` (legado) | 403 | 403 | 403 | 403 | 200/404/422 | ✅ **mas só com a flag ligada** (F1-02) |
| **`/compras/*` (legado)** | **200/404/422** | 200/404/422 | 200/404/422 | 200/404/422 | 200/404/422 | ❌ **qualquer papel, inclusive cliente** (F1-01) |
| **`/atendimentos/*` (legado)** | **200/404/422** | 200/404/422 | 200/404/422 | 200/404/422 | 200/404/422 | ❌ **qualquer papel, inclusive cliente** (F1-01) |
| **`/estoques*`, `/movimentacoes-estoque*`, `/transferencias-estoque*` (legado)** | 403 | 403 | **200/404/409/422** (qualquer loja) | 403 | 403 | ❌ operador sem escopo de loja; gerente/admin bloqueados (F1-03) |

\* corpo vazio não é exigido nessas rotas; 404 aparece porque o id aleatório não existe.

**Rotas legadas que um cliente real alcança (reproduzido):** `GET /compras/pedidos` = 200,
`GET /atendimentos` = 200, `GET /compras/pedidos/{id}/itens` = 200, `GET /compras/pedidos/{id}/pagamentos` = 200;
e passa da autorização (chega ao 422 do corpo) em `POST /compras/pedidos`, `PATCH /compras/pedidos/{id}/status`,
`PATCH /compras/pagamentos/{id}/status`, `POST /atendimentos/{id}/mensagens`, `PATCH /atendimentos/{id}/responsavel`.

**O que deveria ser, segundo o desenho do projeto (`CLAUDE.md` §3):** atendente só atendimento; operador
só estoque da própria loja (aprovar ajuste e definir mínimo são do gerente/admin); gerente tudo da unidade;
admin a rede. O painel novo cumpre isso; as rotas legadas destacadas, não.

---

## 4. O que NÃO foi possível verificar (e o que seria necessário)

| Item | Por quê | O que seria necessário |
|------|---------|------------------------|
| Valor real de `AUTENTICACAO_OBRIGATORIA`, `CORS_ORIGINS`, `DATABASE_URL`, etc. em produção | Variáveis só existem no Render; não li `.env` | Acesso ao painel do Render (ou colar os **nomes e valores não secretos**) |
| Config remota do Supabase Auth: hook ativado, `jwt_expiry`, confirmação de e-mail, captcha, rate limits | Não há SQL/API que leia essa configuração | Acesso ao painel Auth do projeto |
| Buckets/policies de Storage criados à mão | Banco não tem bucket; configuração só no painel | Painel Storage ou exportação |
| `pip-audit` do backend | Bloqueado pela política do Windows | Rodar em CI/Linux |
| Varredura de segredos no histórico completo | Só olhei nomes de arquivo e `.gitignore` | `gitleaks`/`trufflehog` |
| Login real por papel (smoke com contas reais no Supabase, via `signInWithPassword`) | Exigiria usar as senhas das contas e criar sessões no projeto real; a matriz usou tokens ES256 assinados de teste (mesmo formato de claims) com usuários reais **no banco de teste local** | Sua autorização para logar com as contas de teste existentes |
| Comportamento multi-aba/refresh no navegador | Só leitura de código | Teste manual com 2 abas |
| Cabeçalhos HTTP reais em produção | Não chamei a API de produção | `curl -I` contra a URL pública |
| Origem exata do desvio de 8 saldos (F5-01) | Sem log de quem rodou o UPDATE | `pg_stat_statements`/histórico dos scripts de semente |

---

## 5. Plano de correção (ordem de prioridade — nada foi aplicado)

**Prioridade 1 — vazamento de dados e escalada de privilégio (fazer já)**
1. **F1-01 / F1-02 / F2-02:** desmontar de `api_router` os routers legados `compras`, `atendimento`, `admin`, `estoque`, `movimentacoes`, `transferencias` (o front não usa nenhum; o painel novo cobre tudo). Se algum precisar ficar: `trava(Papel.ADMIN)` + `requer_papel` + escopo de loja. *Esforço P.*
2. **F1-02:** fazer `trava` falhar fechada quando houver `SUPABASE_URL`, ignorando `AUTENTICACAO_OBRIGATORIA=false`; conferir o valor no Render hoje. *P.*
3. **F1-03:** (resolvido junto com o item 1.)

**Prioridade 2 — ciclo de vida do acesso e abuso**
4. **F2-01:** ao desativar um usuário, banir/deslogar no Supabase Auth (Admin API) e reduzir `jwt_expiry` (ex.: 15 min); opcional: dependência que confere `ativo` com cache curto. *M.*
5. **F6-01:** instalar o rate limit (por IP e por `sub`), mais baixo em escrita (pedido, chat, chamado). *M.*
6. **F2-04/F2-05:** garantir o trigger de cadastro em cada ambiente; trigger `AFTER DELETE` em `auth.users`; exigir confirmação de e-mail e captcha. *M.*
7. **F1-10/F6-05/F6-06:** desligar `/docs`/`/openapi.json` em produção, handler genérico de erro 500/422 e headers de segurança no front (CSP, `frame-ancestors`, `nosniff`, HSTS). *P/M.*
8. **F1-04:** devolver só disponibilidade (não o saldo exato) em `/cliente/catalogo/estoque`, com cache. *P.*

**Prioridade 3 — integridade**
9. **F5-03:** gravar `valor_frete` (e `canal_venda`) no checkout em colunas, e `valor_total = itens + frete`. *P.*
10. **F5-01/F5-02:** decidir a regra (todo ajuste de saldo gera movimentação); reconciliar os 8 saldos com movimentações de ajuste; ordenar movimentações de forma estável (`criada_em`, `id` sequencial). *M.*
11. **F6-02/F6-03:** versionar bucket e policies de Storage em migration; implementar anexos de chamado pela API (validar dono, MIME, tamanho, prefixo) — ou remover o campo de fotos do formulário. *M.*
12. **F4-01:** FK ou trigger de sincronização `auth.users` → `usuario`. *M.*

**Prioridade 4 — resto**
13. **F1-05, F2-08, F1-07, F1-08:** apagar `backend.ts`/`direto.ts`, unificar os clientes HTTP e tratar 401 num só ponto. *M.*
14. **F1-06:** handler 422 em pt-BR sem eco do corpo. *M.*
15. **F1-09:** paginação / "carregar mais" nas listas com teto. *M.*
16. **F6-14:** lock de dependências (`pip-compile`/`uv`) e `pip-audit` no CI; `gitleaks` no CI. *P.*
17. Testes: cobrir o legado (papel/escopo) e a desativação de usuário com token vivo; teste de concorrência para qualquer rota de estoque que sobrar. *M.*

---

## 6. Correções aplicadas (branches `fix/auditoria-seguranca`, backend e frontend)

Aplicadas a pedido, **em branch própria** (ainda não integradas a `intermediaria`/`develop`). Verificado:
backend 1.138 testes passam; frontend 425 passam; `tsc` e build limpos; `ruff` e `bandit` limpos nos
módulos tocados; a matriz de papéis foi refeita (68 rotas, nenhuma legada).

| Achado | O que foi feito | Evidência |
|--------|-----------------|-----------|
| F1-01, F1-02, F1-03, F2-02, F2-07 | **Removidos** os módulos legados `admin`, `atendimento`, `compras`, `estoque`, `movimentacoes`, `transferencias` (código, rotas e testes) e o mecanismo `trava()` / `AUTENTICACAO_OBRIGATORIA`. Não existe mais modo aberto: sem `SUPABASE_URL` as rotas protegidas respondem 503. Também saiu o código morto que montava SQL com nome de coluna dinâmico (`montar_insert/update`). | `app/api/router.py`; matriz: 140 → 68 rotas, 0 legadas; `bandit` do `app/` sem avisos |
| F2-01, F2-03 | **Vigência do token** (`app/core/vigencia.py`): `requer_papel` confere no banco, com cache de 20 s, que a conta está ativa e com o mesmo cargo e loja do token; divergência → 401 e o front renova a sessão. A Gestão invalida o cache na hora. | `tests/core/test_vigencia.py` (5), `tests/banco/test_http_vigencia_do_token.py` (3, pela API real: desativar e rebaixar derrubam o token já emitido) |
| F6-01 | **Rate limit** próprio (sem dependência nova): por pessoa (hash do token), leitura 120/min, escrita 30/min, escrita sensível (checkout, chamado, agendamento) 10/min, anônimo 300/min; 429 em português com `Retry-After` e com CORS. `slowapi` (nunca usado) saiu do `requirements.txt`. | `app/core/protecoes.py`; `tests/api/test_protecoes_de_borda.py` |
| F6-06, F1-06 | **Cabeçalhos de segurança** em toda resposta; **handler de 500** sem vazamento; **422 em português** só com `{detail, campos}` (sem ecoar o corpo); 404/405 em português. No front, `vercel.json` com `X-Content-Type-Options`, `X-Frame-Options`, HSTS, `Referrer-Policy`, `Permissions-Policy` e CSP de `frame-ancestors`. | testes de borda; `vercel.json` |
| F1-10, F6-05 | `/docs`, `/redoc`, `/openapi.json` **fechados por padrão** (`DOCS_HABILITADAS=true` só em dev). | teste dedicado |
| F5-03 | O checkout agora grava `valor_frete` e `canal_venda`; a migration `20261008110000` corrige pedidos antigos (frete 0 com total acima dos itens). | `tests/banco/test_correcoes_da_auditoria.py` (checkout e idempotência da chave) |
| F2-04, F4-01 | Trigger **`AFTER DELETE` em `auth.users`**: desativa a linha de `usuario` e solta o vínculo (SQL de contingência em `supabase/excluir_conta_trigger.sql`). | teste de banco com `auth.users` simulada |
| F1-05, F2-08, F1-07 | **Um só cliente HTTP** (`lib/api.ts`): `api/http.ts` virou uma camada fina sobre ele (token, renovação em 401, timeout, erros e `Idempotency-Key` em um lugar só). Apagados `api/backend.ts` e `api/direto.ts` (mortos) e o `erroDaResposta` duplicado. | `src/lib/api.test.ts`, `src/api/api.test.ts` |
| F1-08 | **401 tratado num ponto só**: quando a sessão acaba (sem token, ou 401 mesmo depois de renovar), o cliente HTTP chama a sessão e a pessoa volta ao login; removidos os 3 tratamentos 401 por hook. 403/404 não derrubam a sessão. | testes novos em `src/lib/api.test.ts` |
| F6-03 | Já estava resolvido no front atual: o campo de fotos do chamado fica oculto em modo API. | `NovoChamado.tsx` |

### Continua em aberto (e por quê)

| Item | Motivo |
|------|--------|
| F1-04 estoque exato público | Decisão de negócio (o front usa a quantidade). Sugestão: devolver faixa/booleano a anônimos. |
| F2-05 cadastro: confirmação de e-mail/captcha e oráculo de e-mail | Configuração do Supabase Auth, fora do código. |
| F2-01 `jwt_expiry` menor | Configuração do Supabase Auth (a vigência no banco já reduz o risco a ~20 s). |
| F5-01 / F5-02 saldos e encadeamento divergentes | Dados de seed no banco real; correção é de dados (não alterei dados). |
| F6-02 / F6-04 bucket e policies de Storage | Só serão necessários quando o upload de fotos do chamado for implementado de verdade. |
| F6-14 lock de dependências e `pip-audit` | Pendente no CI. |
| F1-09 paginação das listas com teto | Melhoria de UX; sem risco de segurança. |
| F2-09, F2-10, F2-11, F2-12 | Itens menores de UX/resíduos de mock na sessão. |

### Para colocar em produção (depois de integrar as branches)
1. Backend: `git pull`, `alembic upgrade head` (nova revisão `20261008110000`), reiniciar a API.
2. Se o aviso de permissão aparecer na migration: rodar `supabase/excluir_conta_trigger.sql` no SQL Editor.
3. No Render: remover `AUTENTICACAO_OBRIGATORIA` (não existe mais; é ignorada) e, se precisar de `/docs`, definir `DOCS_HABILITADAS=true` só fora de produção.
4. Frontend: deploy normal (o `vercel.json` novo acrescenta os cabeçalhos).
