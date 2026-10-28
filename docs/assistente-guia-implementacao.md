# Guia para implementar os assistentes e o n8n (Entrega 4)

O que já existe no banco, no back e no front para o chat, e como encaixar o resto sem duplicar regra.
Desenho completo: `docs/superpowers/specs/2026-10-27-assistente-base-design.md`. Proposta do time:
`Entrega 4 — Proposta de solução assistentes e automações.pdf`.

## 1. O que já está pronto

| Peça | Onde | Estado |
|---|---|---|
| Tabelas `conversa_assistente` e `mensagem_assistente` | migração `20261027120000` | criadas, vazias |
| `produto.embedding vector(768)` + índice HNSW (cosseno) | idem | coluna criada, **sem embeddings gerados** |
| `loja.horario_funcionamento` | idem + `scripts/semear_horario_lojas.py` | preenchido nas 7 lojas físicas com horário **de referência** (shopping e rua); CD, e-commerce e app sem horário |
| `usuario.aceita_mensagens` | idem + `scripts/importar_aceita_mensagens.py` | 722 "não" da planilha da Vulto; o resto "sim" |
| `aviso_pontos` | idem | o n8n registra aqui o que já avisou |
| Rotas do n8n | `app/automacoes/` | prontas (seção 5) |
| Consultas da diretoria | `app/gerencia/` | vendas, reposição, lojas, estoque parado, pontos a vencer |
| Chaves e destinos de LLM | `Settings.gemini_api_key`, `Settings.groq_api_key`, `assistente_modelo_rapido`, `assistente_modelo_preciso` | opcionais; destinos no formato `provedor:modelo` |
| Classificador e plano de roteamento | `app/assistente/roteamento.py` | implementado e testado; ainda não chama provedores |
| Benchmark de modelos | `scripts/benchmark_chatbot/` | piloto isolado, importa o classificador compartilhado |

## 2. Onde colocar o código

Um módulo novo no padrão dos outros:

```
app/assistente/
  router.py       # rotas /api/v1/assistente/...
  service.py      # loop: historico -> modelo -> ferramentas -> resposta
  ferramentas.py  # cada ferramenta chama um service que ja existe (tabela abaixo)
  provedor.py     # interface unica para Gemini/Groq; os testes usam um provedor falso
  repositorio.py  # leitura e gravacao de conversa_assistente e mensagem_assistente
  schemas.py
```

Registrar o router em `app/api/router.py` com `prefix="/api/v1"`. O teste
`tests/api/test_todas_as_rotas_exigem_login.py` já vai cobrir as rotas novas sozinho.

Rotas sugeridas:

| Método | Rota | Quem |
|---|---|---|
| POST | `/assistente/conversas` | cliente logado, gerente ou admin; o tipo (`cliente`/`interno`) vem do token |
| GET | `/assistente/conversas/{id}` | só o dono da conversa |
| POST | `/assistente/conversas/{id}/mensagens` | só o dono; devolve a resposta do assistente |

## 3. Ferramentas: o que cada uma chama

O modelo escolhe a ferramenta e os argumentos de negócio. **Quem é o usuário, o papel e a loja vêm
sempre do token** (`UsuarioAtual`), nunca de argumento do modelo. Nenhuma ferramenta recebe
`id_cliente`, CPF ou `id_loja` do cliente.

### Assistente do cliente

| Ferramenta | Chama | Observação |
|---|---|---|
| `buscar_produto(descricao)` | **nova**: busca em `produto.embedding` | `ORDER BY embedding <=> :vetor LIMIT 5`, só produto ativo com estoque. Precisa antes do script que gera os embeddings (seção 4) |
| `consultar_estoque(produto, tamanho, loja?)` | `app.cliente.repositorio.listar_estoque_catalogo` | filtrar por variação/tamanho; quantidade já vem sem negativos |
| `info_loja(loja)` | `app.cliente.repositorio.listar_lojas` | traz endereço, telefone e `horario_funcionamento`; `null` = "não tenho o horário dessa loja" |
| `consultar_pontos()` | `app.cliente.service.obter_vulto_mais(conexao, usuario)` | saldo, categoria, quanto falta, `proximos_vencimentos`; dar `commit` (ele lança os vencimentos) |
| `consultar_pedidos()` | `app.cliente.service.listar_pedidos` / `obter_pedido` | só os do cliente do token |
| `montar_carrinho(id_variacao, quantidade)` | `app.cliente.service.adicionar_item_carrinho(conexao, usuario, {...})` | o front chama `sincronizarCarrinho()` (`src/lib/acoes.ts`) e leva para `/checkout` |
| `transferir_para_atendente(motivo)` | `app.cliente.service.criar_chamado(conexao, usuario, {...})` | `assunto` = motivo, `descricao` = resumo de 2 ou 3 linhas + o essencial da conversa, `categoria` de `opcoes_chamado`. Depois gravar `conversa_assistente.status = 'com_atendente'` e `id_atendimento`. O caso cai na fila do painel que já existe e a conversa continua em `/conta/atendimento/{id}` |

### Assistente da diretoria (gerente e admin)

| Ferramenta | Chama | Escopo |
|---|---|---|
| `vendas(loja?, inicio, fim)` | `app.gerencia.service.montar_dashboard` com `Filtro(loja_do_escopo(usuario, id_loja))` | gerente só a própria loja (403 se pedir outra); admin a rede |
| `estoque_parado(dias)` | `app.gerencia.service.montar_estoque_parado` | idem; a resposta já traz `criterio` |
| `pontos_a_vencer(dias)` | `app.gerencia.service.montar_pontos_a_vencer` | **só admin**; só totais |
| `reposicao()` | `app.gerencia.service.montar_reposicao` | idem ao de vendas |
| `lojas()` | `app.gerencia.service.montar_lojas` | idem |

Toda resposta com número deve repetir o critério (período, loja, "sem frete e sem cancelados"). Os
textos prontos ficam em `CRITERIO_*` de `app/gerencia/service.py` e `app/automacoes/service.py`.

## 4. Regras que o código precisa garantir

- **Sem número inventado:** se a ferramenta falhar ou vier vazia, responder "não consegui consultar
  agora". Gravar `mensagem_assistente.sem_resposta = true` quando a pergunta não couber em nenhuma
  ferramenta (vira a lista de "consultas candidatas" da diretoria).
- **Histórico:** mandar ao modelo as últimas N mensagens da conversa (`mensagem_assistente` por
  `criada_em`), não a conversa inteira, para o custo não crescer sem limite.
- **Registro de tudo:** uma linha por mensagem do usuário, por chamada de ferramenta
  (`autor = 'ferramenta'`, `ferramenta`, `dados = {argumentos, resultado}`) e por resposta
  (`modelo`, `tokens_entrada`, `tokens_saida`). É daí que sai o custo real para a apresentação.
- **Dono da conversa:** toda leitura e escrita confere `conversa_assistente.id_usuario` contra o
  usuário do token (a conexão do FastAPI ignora RLS).
- **Texto do usuário e dos dados é dado, não instrução:** nome de produto e mensagem de cliente não
  mudam as regras do prompt.
- **Limite por usuário:** o limitador de `app/core/protecoes.py` é por IP. Para o custo do LLM,
  contar mensagens do usuário no dia em `mensagem_assistente` e responder 429 acima do teto.
- **Embeddings:** 768 dimensões (a coluna é `vector(768)`). Configurar o modelo de embedding para
  essa dimensão; se trocar de modelo, a coluna e o índice mudam numa migração nova. Um script deve
  gerar o embedding de `nome + categoria + cores + tecido + descricao` dos produtos ativos e gravar
  `embedding_em`; regerar quando `produto.atualizado_em > embedding_em`.
- **Testes:** nunca chamar o LLM de verdade. Usar um provedor falso que devolve chamadas de
  ferramenta prontas, no estilo de `tests/automacoes/test_base_assistente.py`.

## 5. n8n (sem IA)

Base: a URL do backend no Render. Cabeçalho em todas as chamadas: `X-Chave-Automacao: <CHAVE_AUTOMACAO>`.

**Aviso de pontos (todo dia às 9h)**
1. `GET /api/v1/automacoes/pontos-a-vencer?canal=email&dias=30` (e `canal=whatsapp`). Já vem só
   quem aceita mensagens, tem o contato do canal e ainda não foi avisado daquele lote.
2. Montar a mensagem com `nome`, `pontos_a_vencer`, `vencimentos[].vence_em`, `categoria`,
   `proxima_categoria` e `faltam_para_proxima`.
3. Enviar.
4. `POST /api/v1/automacoes/avisos-pontos` com
   `{"canal": "email", "avisos": [{"id_cliente", "vence_em", "pontos"}]}`, um item por vencimento
   enviado (copiar `vence_em` exatamente como veio). Repetir o POST não duplica.

**Resumo da diretoria (toda segunda às 8h)**
1. `GET /api/v1/automacoes/resumo-semanal`: semana fechada (segunda a domingo) por loja contra a
   anterior, estoque parado (60 dias) e pontos a vencer (30 dias), cada um com o critério.
2. Enviar por e-mail. Se usar um LLM para o parágrafo de destaques, ele só redige: os números são os
   da resposta.

## 6. Frontend

- **Chat do cliente:** componente no `PortalLayout` (`src/layouts/PortalLayout.tsx`), só para
  cliente logado (`useSessao()?.tipo === "cliente"`). Chamadas em `src/lib/assistenteApi.ts`, no
  padrão dos outros `*Api.ts` (validar a resposta com `src/lib/validacao.ts`).
- **Depois de `montar_carrinho`:** `await sincronizarCarrinho()` e `navigate("/checkout")`.
- **Depois da transferência:** link para `/conta/atendimento/{id_atendimento}`, onde o chat ao vivo
  com o atendente já funciona.
- **Assistente da diretoria:** uma aba ou seção nova no painel, declarada em
  `src/lib/navegacao.ts` com `papeis: ["gerente_loja", "admin"]`.
- **Horário de loja na loja virtual:** `/cliente/lojas` já devolve `horario_funcionamento`.
  `src/lib/horarioLoja.ts` tem o validador e o `resumoHorario()`.

## 7. Configuração

| Variável | Onde | Para quê |
|---|---|---|
| `CHAVE_AUTOMACAO` | Render e n8n | rotas `/automacoes`; sem ela respondem 503 |
| `GEMINI_API_KEY`, `GROQ_API_KEY` | Render | provedores do assistente |
| `ASSISTENTE_MODELO_RAPIDO`, `ASSISTENTE_MODELO_PRECISO` | Render | opcionais; padrao Groq `openai/gpt-oss-20b` para rapida e Gemini `gemini-3.5-flash-lite` para precisa |

Horários de referência: `PYTHONPATH=. python scripts/semear_horario_lojas.py --aplicar` (só preenche
loja sem horário). Os oficiais se ajustam em Gestão → Lojas.
