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
supabase/
├── migrations/
│   └── 20261005000000_criar_tabelas_essenciais.sql
├── seed.sql
└── config.toml

.env.example
.gitignore
requirements.txt
README.md
```

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

## Teste FastAPI da tabela estoque

Esta branch possui um app FastAPI pequeno para exercitar as acoes principais da tabela `estoque`.

Rotas:

- `GET /health`
- `GET /estoques`
- `GET /estoques/<id_estoque>`
- `POST /estoques`
- `POST /estoques/<id_estoque>/entrada`
- `POST /estoques/<id_estoque>/saida`
- `PATCH /estoques/<id_estoque>/minimo`
- `DELETE /estoques/<id_estoque>`

O app le `DATABASE_URL` do `.env`. Esse arquivo nao deve ser versionado.

Para rodar:

```bash
pip install -r requirements.txt
uvicorn estoque_fastapi.app:criar_app --factory --reload
```

Para testar a logica sem tocar no banco remoto:

```bash
pytest tests/test_estoque_repositorio.py
```
