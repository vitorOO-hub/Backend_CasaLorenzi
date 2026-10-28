# Assistente (chat com IA)

Hoje cobre o **vendedor**: rotas em `/api/v1/assistente/vendedor`, só leitura, sempre na loja do token.

| Arquivo | Papel |
|---|---|
| `roteamento.py` | classifica a pergunta e escolhe o destino (`rapida` → Groq, `precisa` → Gemini). Compartilhado |
| `provedores.py` | chamada ao Groq e ao Gemini atrás de `Provedor.conversar(...)`; trata erro e timeout sem vazar corpo nem chave |
| `ferramentas_vendedor.py` | allowlist de ferramentas, schemas de entrada e execução sobre `app.vendas.service` |
| `vendedor.py` | fluxo da pergunta: dono, limite diário, roteamento, modelo, ferramentas, registro |
| `repositorio.py` | `conversa_assistente` e `mensagem_assistente` (sempre filtradas pelo `id_usuario` do token) |
| `router.py` | rotas HTTP (`requer_papel(Papel.VENDEDOR)`) |

## Rotas

| Método | Rota | O que faz |
|---|---|---|
| POST | `/conversas` | novo chat |
| GET | `/conversas` | conversas não arquivadas (título = começo da primeira pergunta) |
| GET | `/conversas/{id}/mensagens` | perguntas e respostas, com as ferramentas usadas |
| POST | `/conversas/{id}/mensagens` | pergunta (`{"texto": "..."}`, até 1000 caracteres) e devolve a resposta |
| PATCH | `/conversas/{id}` | `{"arquivada": true\|false}` |

Conversa de outra pessoa responde 404. Arquivada responde 409 a pergunta nova. Acima de
`LIMITE_PERGUNTAS_POR_DIA` (80) por pessoa, 429.

## Variáveis de ambiente

`GROQ_API_KEY`, `GEMINI_API_KEY`; opcionais `ASSISTENTE_MODELO_RAPIDO` e `ASSISTENTE_MODELO_PRECISO`
(formato `groq:modelo` ou `gemini:modelo`). Sem a chave do destino escolhido, o assistente responde
que está indisponível; não troca de modelo sozinho.

## O que fica registrado

Em `mensagem_assistente`: a pergunta; uma linha por ferramenta chamada (`autor = 'ferramenta'`,
argumentos com CPF mascarado e só um resumo do resultado); e a resposta, com `modelo`, tokens,
`sem_resposta` e em `dados` a decisão de roteamento (`estado`, `rota`, `motivos`), a latência e,
se houver, o status do erro do provedor.

Consulta útil para custo e auditoria:

```sql
SELECT dados->'roteamento'->>'rota' AS rota, modelo, count(*),
       sum(tokens_entrada) AS entrada, sum(tokens_saida) AS saida,
       avg((dados->>'latencia_ms')::int) AS ms
FROM mensagem_assistente WHERE autor = 'assistente' GROUP BY 1, 2;
```

## Como adicionar uma ferramenta

1. Em `ferramentas_vendedor.py`, crie a entrada (subclasse de `_Entrada`, com `extra="forbid"`,
   limites e descrição em cada campo) e a função `(conexao, usuario, entrada) -> dict`.
2. A função chama um service que o vendedor já pode usar e devolve uma saída enxuta: listas curtas,
   sem e-mail ou telefone de cliente, CPF mascarado. **Nunca** aceite loja, usuário ou CPF de escopo
   como argumento: venha do `usuario`.
3. Registre em `_REGISTRO` com uma descrição que diga quando usar.
4. Teste em `tests/assistente/test_chat_vendedor.py` (escopo, argumentos inválidos, campo extra).

## Ainda não feito

- Busca por descrição com embeddings (`produto.embedding` existe, vazio).
- Resumo incremental das mensagens antigas (`conversa_assistente.resumo`); hoje vão as 12 últimas.
- Streaming da resposta (hoje a resposta chega inteira, em JSON).
