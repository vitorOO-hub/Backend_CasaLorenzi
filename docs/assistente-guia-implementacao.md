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
| Chatbot administrativo (backend) | `app/assistente/` | conversas privadas de admin, roteamento Groq/Gemini e ferramentas de consulta; sem frontend |
| Assistente do cliente (backend e site) | `app/assistente/cliente/` | rotas em `/api/v1/assistente/cliente/conversas`; ferramentas de busca, estoque, loja, pontos, pedidos, sacola e transferência; quando não consegue responder, abre chamado com resumo e conversa (`passagem.py`) |

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

Como ficou: o chatbot administrativo usa `/assistente/conversas` (só admin) e o do cliente usa
`/assistente/cliente/conversas` (só cliente), cada um com o próprio contrato. O do cliente tem limite
de 30 mensagens por cliente por dia e conta como escrita sensível no limite por IP. A busca de produto
junta palavras (nome, categoria, cor, tecido, marca) e semelhança por embeddings (ver abaixo).
Sem modelo configurado, ele só avisa que está indisponível; nos demais casos em que não consegue
responder com segurança, passa a conversa para a equipe com o resumo.

Atualizações do assistente do cliente:

- Só para cliente logado (o visitante não vê o assistente). Login do site aceita e-mail ou CPF
  (`/api/v1/acesso/entrar-cpf`).
- Políticas oficiais (trocas, devolução, frete, pagamento, retirada, ajustes, Lorenzi+) ficam em
  `app/assistente/cliente/politicas.md`, lidas pela ferramenta `consultar_politica`. Tema marcado
  como `PENDENTE` faz o assistente passar para a equipe. Um teste confere os números do documento
  contra o código (frete, pontos, categorias).
- Busca semântica: `gemini-embedding-2` com 768 dimensões em `produto.embedding`, o mesmo modelo
  do chatbot do admin (os dois usam a mesma coluna; vetores de modelos diferentes não se comparam)
  (`app/assistente/cliente/embeddings.py`). `scripts/gerar_embeddings_produtos.py` gera os vetores
  das peças sem embedding ou editadas depois dele; rodar de novo após importar ou editar o catálogo.
  Sem embedding (ou com o Gemini fora), a busca por palavras continua sozinha.
- Ao passar para a equipe, o chamado vai para a loja que o cliente citou na conversa
  (`app/assistente/cliente/lojas.py`); sem loja clara, fila geral. Fora do horário cadastrado das
  lojas (`loja.horario_funcionamento`), a resposta diz quando a equipe volta.

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

O chatbot do gerente reutiliza `produto.embedding` nas consultas de reposição e estoque parado:
primeiro tenta localizar o texto nos atributos do catálogo e, sem correspondência, usa similaridade
semântica. Os candidatos e as consultas de estoque são sempre restritos a produtos com registro de
estoque na loja do token; não há acesso do gerente à ferramenta de catálogo global do admin. A chave
`GEMINI_API_KEY` é usada somente no servidor para gerar o vetor da consulta; os embeddings dos produtos
são compartilhados com o chatbot admin e não precisam ser gerados novamente.

O chatbot administrativo foi separado das consultas de gerente e só aceita `Papel.ADMIN`. Ele pode
consultar vendas, estoque/saldo, movimentações, ajustes, transferências, mínimos, reposição, estoque
parado, lojas, pendências, chamados e mensagens, equipe, catálogo, clientes/fichas, auditoria, integrações,
vendas pendentes e totais de pontos a vencer. Toda consulta chama uma função allowlisted do servidor;
não há SQL livre nem ferramenta de escrita. O acesso a cliente usa os serviços de escopo já existentes.

Rotas do backend admin:

| Método | Rota | Função |
|---|---|---|
| POST | `/api/v1/assistente/conversas` | cria conversa privada do admin autenticado |
| GET | `/api/v1/assistente/conversas` | lista até 50 conversas do próprio admin |
| GET | `/api/v1/assistente/conversas/{id}` | lê o histórico do dono da conversa |
| POST | `/api/v1/assistente/conversas/{id}/mensagens` | envia pergunta, consulta ferramentas e retorna resposta |

As chaves de Gemini/Groq são lidas apenas do servidor. Cada pergunta tem limite de 2.000 caracteres;
o histórico enviado ao provedor fica nas 8 últimas mensagens (com teto de 12 mil caracteres); cada resposta pode fazer até quatro
chamadas de ferramenta; e o limite inicial é 25 perguntas por admin/dia. Tokens do provedor ficam
registrados para estimativa de consumo. As conversas e respostas ficam persistidas; os dados brutos
retornados por ferramentas não são gravados no log, e a consulta de cliente não grava o termo buscado.
Como o admin autorizou o envio de dados pessoais identificáveis aos provedores, respostas só devem
incluir esses dados quando forem necessários à pergunta. Avaliar política de retenção/privacidade
antes de disponibilizar o frontend.

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
- **Embeddings do admin:** a busca de catálogo tenta primeiro nome/SKU e, sem resultados, usa
  similaridade semântica em `produto.embedding vector(768)`. Os vetores consideram nome, marca,
  categoria, coleção, tipo, cores e detalhes de tecido; são regenerados quando
  `produto.atualizado_em > embedding_em`. A carga inicial é manual e usa `GEMINI_API_KEY`.
  No PowerShell, simule a leitura (sem chamadas à API ou gravações) e depois aplique em lotes
  pequenos para controlar uso e custo:

  ```powershell
  $env:PYTHONPATH = "."
  python scripts/gerar_embeddings_catalogo.py --limite 5
  python scripts/gerar_embeddings_catalogo.py --limite 5 --aplicar
  ```

  A busca semântica só chama Gemini quando já existem produtos indexados. Alterar o modelo ou a
  dimensão requer migração nova.
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
2. Para o admin, enviar o consolidado da rede. Para cada gerente, repetir a chamada com
   `?id_loja=<UUID>`: vendas e estoque ficam restritos à loja, e `pontos_a_vencer` vem nulo por ser
   um indicador da rede. Enviar por e-mail. Se usar um LLM para o parágrafo de destaques, ele só
   redige: os números são os da resposta.

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
