# Backend_CasaLorenzi

Repositorio do backend e do banco de dados da Casa Lorenzi.

## Objetivo desta branch

Esta branch prepara a estrutura inicial do banco de dados no Supabase/PostgreSQL.

O foco aqui e somente banco de dados:

- criar a estrutura de migrations do Supabase;
- criar as 10 tabelas essenciais do primeiro fluxo;
- incluir constraints, chaves estrangeiras e indices;
- criar um seed pequeno para teste;
- documentar como aplicar a estrutura no Supabase.

Backend em Python e frontend ficam para etapas separadas.

## Estrutura de arquivos

```text
app/                       API FastAPI (monolito modular)
├── main.py                criar_app(): CORS, tratadores de erro e routers
├── core/                  config.py (Settings), db.py (conexao), erros.py (ErroDeNegocio)
├── api/                   router.py (agrega os modulos) e health.py (GET /health)
├── estoque/               router.py, schemas.py, repositorio.py, erros.py
└── atendimento/ compras/ admin/ integracao/ dashboard/   (vazios, proximas etapas)

supabase/
├── migrations/            tabelas, constraints, ids em uuid e politicas de RLS
├── seed.sql
└── config.toml

alembic/                   migrations novas do banco via Alembic

tests/                     core/, api/ e estoque/, espelhando app/
pytest.ini
.env.example
.gitignore
alembic.ini
requirements.txt
README.md
```

Um modulo novo segue o padrao de `app/estoque/`: `router.py` (rotas), `schemas.py` (entrada),
`repositorio.py` (SQL parametrizado) e `erros.py` (subclasses de `ErroDeNegocio`). O router
entra em `app/api/router.py` com uma linha.

## Tabelas principais

A primeira migration cria:

1. `loja`
2. `tipo_usuario`
3. `usuario`
4. `produto`
5. `variacao_produto`
6. `estoque`
7. `status_pedido`
8. `pedido`
9. `item_pedido`
10. `metodo_pagamento`
11. `status_pagamento`
12. `pagamento`
13. `tipo_movimentacao_estoque`
14. `movimentacao_estoque`

As tabelas `tipo_usuario`, `status_pedido`, `metodo_pagamento`, `status_pagamento` e `tipo_movimentacao_estoque` funcionam como listas de opcoes do banco. O frontend pode consultar essas tabelas para montar selects, e as tabelas principais salvam o ID da opcao escolhida.

Tipos iniciais de usuario:

- Cliente
- Operador de estoque
- Atendente
- Gerente da loja
- Diretor

Valores monetarios usam `DECIMAL(12,2)`, evitando `FLOAT` e mantendo duas casas decimais.

## Relacao entre Supabase e codigo Python

O Supabase guarda os dados e protege regras importantes do banco:

- chaves primarias;
- chaves estrangeiras;
- campos obrigatorios;
- valores unicos;
- opcoes controladas por tabelas de dominio;
- checks de quantidade e valores monetarios;
- historico de movimentacao de estoque.

O codigo Python usa essa estrutura para criar as regras da aplicacao:

- receber dados do frontend;
- validar entradas;
- criar clientes, produtos, pedidos e pagamentos;
- chamar o Supabase para consultar e alterar dados;
- executar operacoes sensiveis de forma segura.

Fluxo esperado:

```text
Frontend
  -> Backend Python
    -> Supabase/PostgreSQL
      -> Tabelas, constraints e historico
```

## Versionamento do banco

As migrations SQL em `supabase/migrations/` representam o histórico inicial do projeto.
A partir das próximas mudanças de estrutura do banco, o versionamento deve ser feito pelo Alembic.

Para aplicar as migrations Alembic no banco configurado em `DATABASE_URL`:

```bash
pip install -r requirements.txt
alembic upgrade head
```

Para ver a versão atual do banco:

```bash
alembic current
```

Para criar uma nova migration:

```bash
alembic revision -m "descricao da mudanca"
```

## Como aplicar no Supabase pelo site

Use este caminho se ainda nao estiver usando Supabase CLI.

1. Abra o projeto no painel do Supabase.
2. Entre em `SQL Editor`.
3. Copie o conteudo de `supabase/migrations/20261005000000_criar_tabelas_essenciais.sql`.
4. Execute o SQL.
5. Depois copie o conteudo de `supabase/seed.sql`.
6. Execute o seed para criar dados de teste.
7. Abra `Table Editor` para conferir as tabelas e registros.

Atencao: se o projeto estiver marcado como `PRODUCTION`, revise o SQL antes de executar.

## Como aplicar usando Supabase CLI

Com a Supabase CLI instalada:

```bash
supabase start
supabase db reset
```

Para aplicar em um projeto remoto:

```bash
supabase link --project-ref <project-ref>
supabase db push
```

## Variaveis de ambiente

Copie `.env.example` para `.env` e preencha com os dados do seu ambiente.

Nao coloque no Git:

- senha real do banco;
- `service_role_key`;
- chaves privadas;
- credenciais de producao.

## Decisoes para alinhar com o grupo

- Se usuarios internos poderao pertencer a mais de uma loja.
- Quais opcoes finais serao usadas em `status_pedido`, `status_pagamento`, `metodo_pagamento` e `tipo_movimentacao_estoque`.
- Quando configurar RLS no Supabase.
- Se as tabelas de opcoes terao telas administrativas ou serao mantidas apenas por migration.

## API FastAPI

O modulo `estoque` expoe as acoes principais da tabela `estoque`.

Rotas:

- `GET /health`
- `GET /estoques`
- `GET /estoques/<id_estoque>`
- `POST /estoques`
- `POST /estoques/<id_estoque>/entrada`
- `POST /estoques/<id_estoque>/saida`
- `PATCH /estoques/<id_estoque>/minimo`
- `DELETE /estoques/<id_estoque>`

O app le `DATABASE_URL` (obrigatoria), `SUPABASE_URL` e `CORS_ORIGINS` do `.env`.
Esse arquivo nao deve ser versionado; use `.env.example` como modelo.

Para rodar (documentacao interativa em `http://127.0.0.1:8000/docs`):

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Rode sempre da raiz do projeto. O `app` do modulo `app.main` e criado sob demanda a partir
do `.env`; os testes usam `criar_app(settings)` e nunca leem o `.env`. O comando equivalente
`uvicorn app.main:criar_app --factory --reload` tambem funciona.

Atencao: com `AUTENTICACAO_OBRIGATORIA=false` (o padrao) as rotas de estoque ainda **nao exigem login**
e usam uma conexao que ignora RLS. Rode apenas em `127.0.0.1` nesse modo; para exigir token, veja
a secao "Autenticação (JWT do Supabase)" abaixo.

Para testar sem tocar no banco remoto (os testes nunca leem o `.env`):

```bash
pip install pytest
pytest
```

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
(Authentication → Hooks → Custom Access Token). Sem ele, todo token de equipe vem sem `papel`: em `/admin`, `/estoques` e
`/movimentacoes-estoque` a API responde 403, mas `/atendimentos` e `/compras` aceitam qualquer usuário
autenticado, então um token de equipe sem `papel` passa ali como se fosse cliente. O hook é entregue
pelo Plano 2 (revisão Alembic de RLS e claims).

**Limites conhecidos das claims:**

- O token não traz `ativo`. A equipe inativa perde o `papel` no hook de claims (Plano 2) e passa a ser
  tratada como cliente, então ainda passa em `/atendimentos` e `/compras`. Um cliente inativo mantém o
  acesso até ser banido no Supabase Auth.
- `atendente`, `operador_estoque` e `gerente_loja` precisam de `loja_id` no token. Um atendente
  cadastrado sem loja recebe 401 em todas as rotas com a flag ligada.

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

## Dashboard de atendimento

Alimenta a home do atendente. Todas as rotas exigem o JWT do Supabase e um destes papéis:
`atendente`, `gerente_loja` ou `admin` (mesmo com `AUTENTICACAO_OBRIGATORIA=false`).

| Rota | O que devolve |
|---|---|
| `GET /dashboard/atendimento?inicio=&fim=` | Resumo do período e do período anterior (mesma duração), volume por dia, chamados por categoria, tempo até a primeira resposta por canal, opções de filtro e o escopo do usuário |
| `GET /dashboard/atendimento/fila` | Chamados não finalizados, com contadores (`total_aberto`, `sem_resposta`, `urgentes`), ordenados por prioridade e depois pelos mais antigos |

Filtros opcionais: `id_loja`, `canal` e `categoria` (códigos das tabelas de opções). A fila aceita
`limit` (padrão 20, máximo 100) e `offset`. O período vai de `inicio` a `fim` (datas, inclusivas,
no fuso de São Paulo) e tem no máximo 400 dias.

Escopo (aplicado no código, porque a conexão da API ignora RLS): `atendente` e `gerente_loja`
veem sempre a loja do token e recebem 403 se pedirem outra; `admin` vê a rede inteira ou filtra por
loja. Chamados sem loja (sem pedido) só aparecem para o `admin`. A resposta nunca traz e-mail,
telefone nem documento do cliente.

Definições: "resolvido" é `resolvido` ou `encerrado`; "sem resposta" é o status `aberto`; "primeira
resposta" é a primeira mensagem de alguém que não é cliente; a fila exclui `resolvido`,
`encerrado` e `cancelado`. `atendimento.assunto` é opcional (a revisão `20261007000500` a cria); sem
ele, a fila mostra o nome da categoria.

## Contas de acesso por tipo de usuário

`scripts/criar_contas.py` cria uma conta para cada tipo (cliente, atendente, operador de estoque,
gerente e administrador) pelo Supabase Auth e a liga à linha de `usuario`, de onde o hook de claims
tira o `papel` e a `loja_id` do token. Usa só a chave pública do projeto (nunca a service role).

```bash
python scripts/criar_contas.py             # mostra o plano e não altera nada
python scripts/criar_contas.py --aplicar   # cria as contas e imprime e-mail e senha uma única vez
```

O cadastro público deste projeto está desligado, então a criação usa a Admin API do Supabase, que
precisa da *secret/service role key* (Project Settings > API Keys). Use-a só naquela execução e
nunca grave no `.env` nem no git:

```powershell
$env:SUPABASE_SERVICE_ROLE_KEY = '<chave secreta do painel>'
python scripts/criar_contas.py --email-base voce@gmail.com --aplicar
Remove-Item Env:SUPABASE_SERVICE_ROLE_KEY
```

Alternativa sem a chave: crie as contas no painel (Authentication > Users > Add user, com Auto
Confirm) e rode `python scripts/criar_contas.py --email-base voce@gmail.com --so-vincular --aplicar`,
que só liga cada conta à sua linha em `usuario`.

As senhas são geradas na hora e só aparecem na saída do comando; guarde-as em um gerenciador de
senhas. Quem já tem conta no Auth é pulado (sem a service role não há como ler nem trocar a senha de
outra conta; para recuperar o acesso, use "Reset password" no painel do Supabase). Se o projeto
exigir confirmação de e-mail, o script avisa: desligue "Confirm email" em Authentication > Providers
> Email, ou confirme as contas no painel.

## Chamados do painel (atendente, gerente e admin)

Rotas em `/api/v1/painel/atendimentos`, sempre com token e papel `atendente`, `gerente_loja` ou
`admin` (independente de `AUTENTICACAO_OBRIGATORIA`). O remetente, o papel e a loja vêm do token,
nunca do corpo.

| Rota | O que faz |
|---|---|
| `GET /opcoes` | status, canais, categorias, prioridades e lojas para os filtros |
| `GET /resumo` | contadores: sem resposta, em andamento, prioridade alta, resolvidos, na fila, meus |
| `GET /` | lista paginada; filtros `situacao`, `responsavel` (`fila`, `eu`, `todos`), `prioridade`, `canal`, `categoria`, `id_loja` |
| `GET /{id}` | detalhe: cliente, pedido, peças, anexos, outros chamados e (só gerente/admin) compras |
| `GET /{id}/mensagens` | conversa em ordem |
| `POST /{id}/mensagens` | responder; quem responde primeiro assume o chamado e ele sai de "aberto" |
| `POST /{id}/assumir` | assume; 409 se outra pessoa chegou antes |
| `POST /{id}/resolver` | resolve; atendente só o que assumiu, gestão qualquer um |

Escopo: atendente e gerente veem a própria loja **e os chamados sem loja**; o admin vê a rede e
pode filtrar por loja. Chamado fora do escopo responde 404. As escritas travam a linha
(`FOR UPDATE`): duas pessoas assumindo ao mesmo tempo resultam em um sucesso e um 409.

Campos novos (revisão `20261007000600`): `atendimento.protocolo` (`AT-AAAA-NNNN`, gerado por
trigger), `usuario.cidade` e a tabela `chamado_anexo` (com RLS).

`python scripts/semear_chamados.py --aplicar` cria chamados de exemplo para ver a fila funcionando
(só se a tabela estiver vazia; só para desenvolvimento).

## Chat ao vivo do atendente

O chat usa o **Supabase Realtime** (sem servidor de websocket proprio). A API cuida da sessao, da
caixa de conversas e da escrita; o Realtime entrega o que acontece ao vivo.

### Endpoints (`/api/v1/painel/chat`, privados: atendente, gerente e admin)

| Metodo | Rota | Para que serve |
| --- | --- | --- |
| GET | `/conversas?secao=todas\|fila\|minhas&apenas_nao_lidas=&limit=&offset=` | Caixa de conversas abertas (ultima mensagem, nao lidas, aguardando resposta) |
| GET | `/conversas/resumo` | Contadores da caixa: fila, minhas, nao lidas, aguardando |
| GET | `/conversas/{id}/sessao` | Abre a sessao do chat: canal privado, filtro do Realtime, quem sou eu, se posso responder |
| GET | `/conversas/{id}/mensagens?apos=<id>&limit=` | Historico e recuperacao apos reconexao (cursor por mensagem) |
| POST | `/conversas/{id}/mensagens` | Envia mensagem (assume o chamado se estiver sem responsavel) |
| POST | `/conversas/{id}/lido` | Marca a conversa como lida para quem chamou |

Escopo: equipe ve a propria loja e os chamados sem loja; admin ve a rede; conversa fora do escopo
devolve 404. O remetente sempre vem do token, nunca do corpo.

### Como o front se conecta

1. `GET /conversas/{id}/sessao` devolve `topico` (`chamado:<uuid>`) e `filtro_mensagens`.
2. **Mensagens novas**: Postgres Changes em `public.mensagem` com o filtro recebido. O RLS decide
   quem recebe.
3. **Digitando e presenca**: canal **privado** `supabase.channel(topico, { config: { private: true } })`
   (Broadcast e Presence). As policies em `realtime.messages` so liberam quem enxerga o chamado.
4. Apos reconectar, `GET /mensagens?apos=<ultimo_id_mensagem>` busca o que ficou pendente.

### Banco

Migration `20261007120000_chat_ao_vivo`: tabela `chamado_leitura` (RLS forcado, fechada ao front),
`mensagem` e `atendimento` na publicacao `supabase_realtime` e as policies de `realtime.messages`.
Se faltar permissao para criar as policies, a migration avisa e segue: rode
`supabase/realtime_chat_policies.sql` pelo SQL Editor. A revisao encadeia depois de
`20261007110000` (correcao de RLS das transferencias).

## Início do gerente (vendas, reposição e pendências)

Rotas privadas em `/api/v1/painel/gerencia`, só para `gerente_loja` e `admin`. O gerente enxerga
sempre a própria loja (a do token; pedir outra dá 403); o admin vê a rede ou escolhe uma loja.

| Método | Rota | Para que serve |
| --- | --- | --- |
| GET | `/dashboard?inicio=&fim=&categoria=&canal=&id_loja=` | Faturamento, pedidos, ticket médio e peças do período contra o anterior; série diária; movimento por dia da semana; peças mais vendidas; mix loja × online; opções de filtro |
| GET | `/reposicao?categoria=&limit=` | Peças que acabam primeiro: saldo contra o ritmo de venda dos últimos 30 dias |
| GET | `/pendencias` | Ajustes a aprovar, transferências aguardando a loja e chamados sem resposta |

Os chamados da unidade (por motivo, taxa de resolução, primeira resposta) já vêm de
`GET /dashboard/atendimento`, que o gerente também pode usar.

Regras: venda é pedido `pago`, `separado` ou `entregue`; o faturamento soma os itens (sem frete) e o
dia é o de São Paulo. A migration `20261007130000` cria `pedido.canal_venda` (`loja`/`online`),
`pedido.valor_frete` e a tabela `ajuste_estoque` (RLS forçado, sem acesso do front).

### Dados de exemplo

```
python scripts/semear_vendas.py             # mostra o que seria criado
python scripts/semear_vendas.py --aplicar   # grava (uma transação, uma única vez)
```

Cria 2 lojas, o catálogo da coleção, clientes fictícios (sem login), ~13 meses de pedidos com
pagamentos e movimentações de estoque coerentes, ajustes a aprovar e transferências. Exige
`alembic upgrade head`.
