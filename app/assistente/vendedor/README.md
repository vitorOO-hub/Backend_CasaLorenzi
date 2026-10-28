# Assistente (chat com IA)

Hoje cobre o **vendedor**: rotas em `/api/v1/assistente/vendedor`, só leitura, sempre na loja do token.

| Arquivo | Papel |
|---|---|
| `roteamento.py` | classifica a pergunta e escolhe o destino (`rapida` → Groq, `precisa` → Gemini). Compartilhado |
| `provedores.py` | chamada ao Groq e ao Gemini atrás de `Provedor.conversar(...)`; trata erro e timeout sem vazar corpo nem chave |
| `ferramentas.py` | allowlist de ferramentas, schemas de entrada e execução sobre `app.vendas.service` |
| `service.py` | fluxo da pergunta: dono, limite diário, roteamento, modelo, ferramentas, registro |
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

1. Em `ferramentas.py`, crie a entrada (subclasse de `_Entrada`, com `extra="forbid"`,
   limites e descrição em cada campo) e a função `(conexao, usuario, entrada) -> dict`.
2. A função chama um service que o vendedor já pode usar e devolve uma saída enxuta: listas curtas,
   sem e-mail ou telefone de cliente, CPF mascarado. **Nunca** aceite loja, usuário ou CPF de escopo
   como argumento: venha do `usuario`.
3. Registre em `_REGISTRO` com uma descrição que diga quando usar.
4. Teste em `tests/assistente/test_chat_vendedor.py` (escopo, argumentos inválidos, campo extra).

## Contagem de estoque (`consultar_estoque`, `estoque.py`)

Toda pergunta de quantidade ("quantas peças G", "tem camisa G?", "sobrou GG?") passa por uma
consulta só: o modelo manda os filtros como o vendedor falou e o backend faz o resto.

- **Normalização** (`normalizar_tamanho`, `normalizar_categoria`): os valores válidos vêm do banco
  a cada consulta (`catalogo()`), nada fixo no código. "tam g", "grande" e "g" viram `G`; "G" nunca
  casa com "GG" (igualdade exata). "roupas", "peças" e "vestuário" valem todas as categorias,
  menos `pendente_identificacao`. Plural, acento e erro de digitação leve ("camsias") caem na
  categoria real mais parecida.
- **Soma no SQL** (`contar`): unidades disponíveis (quantidade > 0) de variação e produto ativos,
  na loja que recebe as vendas do vendedor. Não há reserva nem bloqueio no sistema. Texto do
  vendedor só entra como parâmetro.
- **Zero nunca é cego**: filtro inexistente volta como `filtro_invalido` (sem contagem) com os
  `valores_validos`; zero com filtro válido volta como `zero_confirmado`. Erro da ferramenta vira
  "não consegui consultar", nunca zero.
- **Conferência** (`conferencia.conferir_estoque`): se a resposta não traz o número da ferramenta,
  diz "não há" sem zero confirmado ou trata erro/filtro inexistente como zero, vale o texto
  montado pelo backend.
- **Revisão**: respostas de zero ou "não há" ficam com `dados.revisar_zero = true`; o 👍/👎 do
  vendedor fica em `dados.avaliacao` (`util` ou `nao_util`).

Para conferir de perto:

```sql
SELECT m.criada_em, p.texto AS pergunta, m.texto AS resposta, m.dados->>'avaliacao' AS avaliacao
FROM mensagem_assistente m
JOIN LATERAL (
    SELECT texto FROM mensagem_assistente u
    WHERE u.id_conversa = m.id_conversa AND u.autor = 'usuario' AND u.criada_em < m.criada_em
    ORDER BY u.criada_em DESC LIMIT 1
) p ON true
WHERE m.autor = 'assistente' AND (m.dados->>'revisar_zero' = 'true' OR m.dados ? 'avaliacao')
ORDER BY m.criada_em DESC;
```

### Como adicionar um filtro ou atributo

1. Campo novo em `EntradaEstoque` (`ferramentas.py`), opcional, com descrição de como o vendedor
   fala.
2. Em `estoque.py`: no `Filtro` e em `_condicoes`, sempre como parâmetro (`:nome`), nunca
   concatenado. Para agrupar por ele, uma coluna fixa em `_COLUNA` e o valor no `Literal` de
   `agrupar_por`.
3. Se o valor tiver lista fechada (como tamanho), leia os válidos em `catalogo()` e normalize como
   `normalizar_tamanho`, devolvendo `filtro_invalido` quando não existir.
4. Teste o caso crítico em `tests/assistente/test_chat_vendedor.py` e acrescente perguntas ao golden
   set em `scripts/avaliar_estoque_vendedor.py`.

### Golden set (modelo real, fora do CI)

```bash
.venv/Scripts/python.exe scripts/avaliar_estoque_vendedor.py --saida relatorio.md
```

Compara cada resposta com uma contagem SQL independente da ferramenta. Fica fora do CI porque chama
Groq/Gemini; o CI cobre a ferramenta, a normalização e a conferência com modelo falso.

## Ainda não feito

- Busca por descrição com embeddings (`produto.embedding` existe, vazio): quando houver, só para
  casar nome aproximado de produto; a contagem continua em `consultar_estoque`.
- Resumo incremental das mensagens antigas (`conversa_assistente.resumo`); hoje vão as 12 últimas.
- Streaming da resposta (hoje a resposta chega inteira, em JSON).
