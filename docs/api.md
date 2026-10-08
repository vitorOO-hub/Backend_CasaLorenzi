# Referência da API

Base: `https://backend-casalorenzi.onrender.com` (produção) ou `http://127.0.0.1:8000` (local).
Para ver o contrato completo, com todos os campos de cada rota, ligue `DOCS_HABILITADAS=true` em
desenvolvimento e abra `/docs`.

## Convenções

- **Autenticação:** `Authorization: Bearer <jwt do Supabase>` em toda rota, exceto `GET /health` e `GET /api/v1/cliente/catalogo/estoque`.
- **Quem faz a ação** (usuário, papel e loja) vem sempre do token. O corpo nunca aceita `papel`, `id_loja` do usuário nem `id_cliente`; campos desconhecidos geram `422`.
- **Paginação:** `limit` (padrão 20, máximo 100) e `offset`.
- **Códigos de erro:**

| Código | Quando |
|---|---|
| `401` | token ausente, inválido, expirado, ou conta inativa/com cargo diferente do token |
| `403` | papel ou loja sem permissão |
| `404` | não existe **ou** está fora do escopo de quem pediu |
| `409` | o estado atual não permite a ação (ajuste já decidido, chamado já assumido, saldo insuficiente) |
| `422` | validação: `{ "detail": "...", "campos": [{ "campo": "...", "mensagem": "..." }] }` |
| `429` | limite de requisições; veja o header `Retry-After` |

- **Escopo de loja:** operador, atendente e gerente veem a própria loja (pedir outra dá `403`); o admin vê a rede ou escolhe com `id_loja`.
- **Escritas concorrentes** travam a linha (`FOR UPDATE`): duas pessoas agindo ao mesmo tempo resultam em um sucesso e um `409`.

Legenda de quem acessa: **A** atendente · **O** operador de estoque · **G** gerente · **D** admin · **C** cliente logado.

---

## Saúde

| Método | Rota | Quem | O que faz |
|---|---|---|---|
| GET | `/health` | público | `{"status": "ok"}`; usado pelo health check do Render |

## Loja do cliente — `/api/v1/cliente`

Qualquer pessoa logada; todos os dados são os do dono do token.

| Método | Rota | O que faz |
|---|---|---|
| GET | `/catalogo/estoque` | **público.** Disponibilidade das peças por loja |
| GET | `/lojas` | lojas disponíveis para retirada e entrega |
| GET | `/perfil` | dados e endereço de quem está logado |
| GET | `/carrinho` | itens da sacola |
| POST | `/carrinho/itens` | adiciona uma peça |
| PATCH | `/carrinho/itens/{id_variacao}` | muda a quantidade |
| DELETE | `/carrinho/itens/{id_variacao}` | remove uma peça |
| DELETE | `/carrinho` | esvazia a sacola |
| POST | `/pedidos` | **checkout transacional.** Cria pedido, itens e pagamento e baixa o estoque da loja. Aceita `Idempotency-Key` |
| GET | `/pedidos` | pedidos do cliente |
| GET | `/pedidos/{id_pedido}` | detalhe de um pedido seu |
| GET | `/chamados/opcoes` | motivos e prioridades para abrir chamado |
| POST | `/chamados` | abre chamado (pedido e peça de contexto são validados como seus) |
| GET | `/chamados` | seus chamados |
| GET | `/chamados/{id_atendimento}` | detalhe de um chamado seu |
| GET | `/chamados/{id_atendimento}/mensagens` | conversa |
| POST | `/chamados/{id_atendimento}/mensagens` | envia mensagem |
| GET | `/agendamentos/opcoes` | tipos e horários disponíveis |
| POST | `/agendamentos` | agenda ajuste ou prova de peça |

Valores de entrega e frete vêm do servidor; o total do pedido é a soma dos itens mais o frete. O
preço e o nome da peça ficam gravados no item na hora da compra.

## Chamados do painel — `/api/v1/painel/atendimentos` (A, G, D)

| Método | Rota | O que faz |
|---|---|---|
| GET | `/opcoes` | status, canais, categorias, prioridades e lojas para os filtros |
| GET | `/resumo` | contadores: sem resposta, em andamento, prioridade alta, resolvidos, na fila, meus |
| GET | `/` | lista paginada. Filtros: `situacao`, `responsavel` (`fila`, `eu`, `todos`), `prioridade`, `canal`, `categoria`, `id_loja` |
| GET | `/{id}` | detalhe: cliente, pedido, peças, anexos e outros chamados. Compras só para G e D |
| GET | `/{id}/mensagens` | conversa em ordem |
| POST | `/{id}/mensagens` | responde; quem responde primeiro assume o chamado |
| POST | `/{id}/assumir` | assume; `409` se outra pessoa chegou antes |
| POST | `/{id}/resolver` | resolve; atendente só o que assumiu, gestão qualquer um |

A e G veem a própria loja **e os chamados sem loja**; D vê a rede.

## Chat do atendimento — `/api/v1/painel/chat` (A, G, D)

O tempo real vem do Supabase Realtime; a API entrega a sessão, a caixa de conversas e a escrita.

| Método | Rota | O que faz |
|---|---|---|
| GET | `/conversas?secao=todas\|fila\|minhas&apenas_nao_lidas=` | caixa de conversas (última mensagem, não lidas) |
| GET | `/conversas/resumo` | contadores da caixa |
| GET | `/conversas/{id}/sessao` | canal privado `chamado:<uuid>`, filtro do Realtime e se pode responder |
| GET | `/conversas/{id}/mensagens?apos=<id>` | histórico e recuperação após reconexão (cursor) |
| POST | `/conversas/{id}/mensagens` | envia mensagem (assume o chamado se estiver sem responsável) |
| POST | `/conversas/{id}/lido` | marca como lida |

## Clientes do painel — `/api/v1/painel/clientes` (A, G, D)

| Método | Rota | O que faz |
|---|---|---|
| GET | `/` | lista. Filtros: `busca` (nome, e-mail, telefone), `secao` (`todos`, `com_aberto`, `meus`), `id_loja` (só D) |
| GET | `/{id}` | ficha: contato, resumo, chamados do escopo |

**Privacidade:** compras, total gasto e ticket médio só chegam para G e D (para o atendente vêm nulos e
nem são calculados). O documento (CPF) nunca é devolvido.

## Estoque do painel — `/api/v1/painel/estoque` (O, G, D)

| Método | Rota | Quem | O que faz |
|---|---|---|---|
| GET | `/opcoes` | O, G, D | categorias, peças, tipos, lojas e o escopo de quem chamou |
| GET | `/saldo` | O, G, D | resumo e saldo por peça (coluna por loja para o admin). Filtros: `busca`, `categoria`, `situacao`, `id_loja` |
| GET | `/movimentacoes` | O, G, D | histórico com saldo antes e depois. O operador vê só as que ele registrou |
| POST | `/movimentacoes` | O, G, D | registra **entrada ou saída** e já muda o saldo. A saída valida o saldo |
| GET | `/ajustes?situacao=` | O (só os seus), G, D | pedidos de ajuste e quantos estão pendentes |
| POST | `/ajustes` | O, G, D | **pede ajuste** de inventário informando a quantidade contada; o saldo não muda agora |
| POST | `/ajustes/{id}/aprovar` | G, D | aplica a diferença ao saldo de agora e lança a movimentação |
| POST | `/ajustes/{id}/recusar` | G, D | recusa com motivo; o estoque não muda |
| GET | `/transferencias?situacao=acao\|andamento\|todas` | O, G, D | transferências e reposições, com as ações possíveis para quem consulta |
| POST | `/transferencias` | O, G, D | a loja de destino pede peças a uma origem |
| POST | `/transferencias/reposicoes` | O, G, D | pedido de reposição à rede toda |
| POST | `/transferencias/{id}/aceitar` | O, G, D | a origem aceita: a peça **sai** do estoque dela |
| POST | `/transferencias/{id}/recusar` | O, G, D | a origem recusa; o estoque não muda |
| POST | `/transferencias/{id}/receber` | O, G, D | o destino confirma: a peça **entra** no estoque dele |
| GET | `/minimos` | G, D | estoque mínimo por peça |
| PUT | `/minimos` | G, D | define o mínimo (tudo ou nada) |

Situação da peça: `esgotado` (saldo 0), `baixo` (no mínimo ou abaixo) e `ok`. Nenhuma operação deixa o
saldo negativo (`409 Saldo insuficiente`), e repetir uma etapa de transferência ou decidir um ajuste
já decidido devolve `409`.

**Fluxo do ajuste de inventário:** o **operador** pede (com motivo) → o **gerente** da mesma loja ou o
admin aprova ou recusa. A tela só oferece o botão de pedir ao operador; a rota hoje também aceita G e D.

## Gerência — `/api/v1/painel/gerencia` (G, D)

| Método | Rota | O que faz |
|---|---|---|
| GET | `/dashboard?inicio=&fim=&categoria=&canal=&id_loja=` | faturamento, pedidos, ticket médio e peças contra o período anterior; série diária; dia da semana; mais vendidas; mix loja × online |
| GET | `/reposicao?categoria=&limit=` | peças que acabam primeiro (saldo contra o ritmo dos últimos 30 dias) |
| GET | `/pendencias` | ajustes a aprovar, transferências aguardando a loja e chamados sem resposta |
| GET | `/lojas` | cartão de cada loja |
| GET | `/rede` | **só D.** Início do admin: a rede e as lojas |

Venda é pedido `pago`, `separado` ou `entregue`; o faturamento soma os itens, sem frete.

## Gestão — `/api/v1/painel/gestao` (somente D)

| Método | Rota | O que faz |
|---|---|---|
| GET | `/usuarios` | time interno: cargo, unidade e acesso |
| PATCH | `/usuarios/{id}` | muda cargo, unidade ou acesso. Vale em segundos (invalida o cache de vigência). Não deixa desativar ou rebaixar a própria conta nem o último administrador |
| GET | `/catalogo` | peças e preços do catálogo |
| POST | `/catalogo` | nova peça (SKU e nome não podem repetir: `409`) |
| PATCH | `/catalogo/{id_produto}` | edita a peça |
| DELETE | `/catalogo/{id_produto}` | exclui; `409` se a peça tiver estoque, pedidos ou histórico de estoque |
| GET | `/auditoria` | quem fez o quê e quando |
| GET | `/integracoes` | lotes do ERP e registros a mapear |
| POST | `/integracoes/registros/{id}/mapear` | liga um código do ERP a um SKU da Casa Lorenzi |

Mudanças de usuário e de catálogo gravam um registro de auditoria.

## Dashboard de atendimento — `/dashboard/atendimento` (A, G, D)

| Método | Rota | O que faz |
|---|---|---|
| GET | `/dashboard/atendimento?inicio=&fim=` | resumo do período e do anterior, volume por dia, chamados por categoria, primeira resposta por canal |
| GET | `/dashboard/atendimento/fila` | chamados não finalizados com contadores, por prioridade e antiguidade |

Filtros opcionais: `id_loja`, `canal`, `categoria`. O período tem no máximo 400 dias e usa o fuso de
São Paulo. A resposta nunca traz e-mail, telefone ou documento do cliente.
