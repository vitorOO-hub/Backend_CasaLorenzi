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

Atencao: as rotas de estoque ainda **nao exigem login** e usam uma conexao que ignora RLS.
Rode apenas em `127.0.0.1` ate a autenticacao do Supabase entrar.

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
(Authentication → Hooks → Custom Access Token). Sem ele, todo token de equipe vem sem `papel` e a
API responde 403. O hook é entregue pelo Plano 2 (revisão Alembic de RLS e claims).
