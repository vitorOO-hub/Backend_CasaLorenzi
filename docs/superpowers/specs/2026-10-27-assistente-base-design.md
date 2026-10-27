# Base para os assistentes e as automações (Entrega 4)

Data: 27/10/2026. Escopo: só a base de banco, back e front que os assistentes (cliente e diretoria) e
as automações do n8n vão usar. O assistente em si (chamadas ao LLM, prompts, chat na tela) fica para
a etapa seguinte.

## Decisões

- **Consentimento de mensagens:** quem não tem informação conhecida fica como `sim`. Só fica `não`
  quem a planilha da Vulto marcou explicitamente como não (`N`, `nao`, `0`) ou com "não ligar" na
  observação. O cliente pode mudar a escolha no perfil.
- **As consultas ficam em endpoints do FastAPI**, não em funções SQL novas. O n8n e os assistentes
  chamam o mesmo service, então a regra de pontos continua num lugar só
  (`app/cliente/vencimento_pontos.py`).
- **Chaves de LLM** (`GEMINI_API_KEY`, `GROQ_API_KEY`) já estão no `.env`; entram em `Settings` como
  opcionais, sem uso nesta etapa.

## Banco (migração `20261027120000_assistente_base`)

| Mudança | Para quê |
|---|---|
| `usuario.aceita_mensagens boolean NOT NULL DEFAULT true`, `aceita_mensagens_origem text` (`padrao`, `planilha_vulto`, `cliente`), `aceita_mensagens_em timestamptz` | Filtrar os avisos (LGPD) e saber de onde veio a escolha |
| `aviso_pontos (id_aviso, id_usuario, vence_em, pontos, canal, enviado_em)`, `UNIQUE (id_usuario, vence_em, canal)` | O n8n não repete o aviso do mesmo lote |
| `CREATE EXTENSION vector`; `produto.embedding vector(768)`, `produto.embedding_em`; índice HNSW (cosseno) | Busca por descrição ("camisa azul de botão") |
| `loja.horario_funcionamento jsonb` (objeto `seg`..`dom` → `{abre, fecha}` ou `null`) | `info_loja` lê o horário do banco |
| `conversa_assistente (id_conversa, id_usuario, tipo, status, id_atendimento, resumo, criada_em, atualizada_em)` | Histórico e passagem para atendente |
| `mensagem_assistente (id_mensagem, id_conversa, autor, texto, ferramenta, dados jsonb, sem_resposta, modelo, tokens_entrada, tokens_saida, criada_em)` | Memória da conversa, perguntas sem resposta e custo |

As tabelas novas têm RLS ligado e forçado, sem policies: só o FastAPI (que ignora RLS) lê e grava.

O consentimento da planilha entra por `scripts/importar_aceita_mensagens.py`, que casa pelo CPF
(`usuario.documento`) e grava só os `não` explícitos (o resto já é `sim` pelo default).

## Backend

**Autenticação das automações:** dependência `requer_automacao`, com cabeçalho `X-Chave-Automacao`
comparado em tempo constante com `CHAVE_AUTOMACAO`. Sem cabeçalho: 401. Sem chave configurada: 503.
O teste de "toda rota exige login" continua valendo sem exceção nova.

**Endpoints novos**

| Rota | Quem | Faz |
|---|---|---|
| `GET /api/v1/automacoes/pontos-a-vencer?dias=30&canal=email` | n8n | Clientes ativos que aceitam mensagens, com pontos vencendo nos próximos `dias` e ainda não avisados nesse canal: nome, contato, pontos, data, categoria e quanto falta para a próxima |
| `POST /api/v1/automacoes/avisos-pontos` | n8n | Registra os avisos enviados (idempotente) |
| `GET /api/v1/automacoes/resumo-semanal` | n8n | Vendas da última semana fechada por loja e canal contra a anterior, estoque parado e pontos a vencer |
| `GET /api/v1/painel/gerencia/estoque-parado?dias=60` | gerente, admin | Peças com saldo e sem venda há `dias` dias, no escopo de loja do token |
| `GET /api/v1/painel/gerencia/pontos-a-vencer?dias=30` | admin | Total de clientes e pontos que vencem, por data, e os maiores casos |
| `PATCH /api/v1/cliente/preferencias` | cliente | Muda `aceita_mensagens` (origem `cliente`) |
| `PATCH /api/v1/painel/gestao/lojas/{id}/horario` | admin | Grava o horário de funcionamento, com auditoria |

Mudanças em respostas existentes: `/cliente/perfil` traz `aceita_mensagens`; `/cliente/lojas` e
`/painel/gerencia/lojas` trazem `telefone` e `horario_funcionamento`.

Critérios dos números, iguais aos do painel: venda = pedido `pago`, `separado` ou `entregue`, sem
frete. Estoque parado = saldo > 0 e nenhuma venda da variação naquela loja no período. Pontos a vencer
usa a mesma conta de lotes do Lorenzi+.

## Frontend

- Perfil do cliente: opção "Aceito receber avisos dos meus pontos por e-mail e WhatsApp".
- Gestão → Lojas: o horário aparece no cartão e o admin pode editar.
- Funções de API com validação, no padrão de `src/lib/*Api.ts`.

## Fora desta etapa

Chamadas ao LLM, geração dos embeddings, endpoints de conversa do assistente, componente de chat e
os fluxos do n8n. Os dados e as rotas acima são o que eles vão consumir.

## Testes

- Backend: rotas novas com o banco simulado (papel, escopo, 401 sem chave), validação do horário,
  conta de pontos a vencer em lote com movimentos fictícios, regra do consentimento da planilha.
- Front: validação das respostas novas e montagem do horário.
- Migração aplicada no Supabase e conferida com uma leitura das colunas e tabelas novas.
