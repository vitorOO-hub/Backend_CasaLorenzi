# Benchmark isolado do chatbot

Este piloto compara Gemini e Gemma por padrao, com as mesmas perguntas e fixtures inteiramente ficticias. Groq e Anthropic continuam disponiveis como opcoes explicitas. O benchmark nao acessa o banco, nao chama endpoints da plataforma e nao altera o deploy.

As chaves e modelos sao configurados no `.env` local. Gemini e Gemma usam a mesma `GEMINI_API_KEY`, mas identificadores de modelo distintos. Os resultados CSV ficam em `scripts/benchmark_chatbot/resultados/`. Nenhum dos scripts acessa banco, endpoints da plataforma ou deploy.

## Modos de teste

- `run.py`: baseline com contexto ficticio no prompt, sem chamar ferramentas.
- `run_tools.py`: envia definicoes de ferramentas simuladas para medir se o modelo escolhe a funcao e os argumentos esperados, alem de avaliar a resposta final. Todas as respostas das funcoes sao fixtures locais ficticias.

O segundo modo pode fazer mais de uma requisicao por caso (uma para solicitar a ferramenta e outra para responder com o resultado). Comece com uma repeticao; os custos de API, caso as chaves estejam configuradas, sao reais. As estimativas de custo so aparecem se as tarifas por milhao de tokens forem preenchidas e nao incluem eventuais diferencas de cobranca entre modelos.

## Criterios de roteamento (piloto local)

O modulo `classificacao_perguntas.py` separa capacidade do modelo da necessidade de consultar dados. Ele apenas classifica; nao chama provedores, nao executa ferramentas e nao autoriza acesso a dados.

| Decisao | Criterio | Exemplo |
| --- | --- | --- |
| `rapida` | Pergunta direta, de um passo, sem analise, ambiguidade ou dado pessoal/financeiro. Uma consulta simples pode usar ferramenta e continuar na rota rapida. | "Quantas unidades da CAM-001 temos na Savassi?" |
| `precisa` | Pede comparacao, explicacao, estimativa ou raciocinio em varias etapas; envolve pontos, pedido/saldo pessoal ou metricas financeiras; ou tenta obter/inventar dado protegido. | "Compare as vendas dos meses e explique a diferenca." |
| `esclarecer` | Falta identificar o produto/pedido ou a pergunta esta vazia. Pedir o detalhe faltante antes de gastar uma chamada de modelo. | "Tem essa peca na loja?" |

`classificacao_perguntas.py` importa o classificador compartilhado em `app/assistente/roteamento.py`. O plano de roteamento tambem pode selecionar um destino `provedor:modelo`, mas nao chama a API. `requer_ferramenta` e independente da rota: estoque, preco atual, pontos, pedido, horario e indicadores consultaveis sao marcados para ferramenta quando a pergunta inclui dados suficientes. A ferramenta deve aplicar autenticacao, autorizacao e escopo no backend. A classificacao nunca concede permissao. Casos incertos devem ir para `precisa` ou pedir esclarecimento, nao para a rota rapida.

Este e um primeiro classificador heuristico, nao uma decisao final de producao. Ele deve ser avaliado com perguntas reais anonimizadas e exemplos de cada intencao. Os destinos padrao usam Groq `openai/gpt-oss-20b` na rota rapida e Gemini `gemini-3.5-flash-lite` na rota precisa; podem ser sobrescritos por ambiente. O plano nao faz chamadas externas nem fallback silencioso.

Para a comparacao atual, configure no `.env` local. A Groq tem limites de uso no plano gratuito; nao faca upgrade para o plano Developer se a ideia e evitar cobrancas.

    GEMINI_API_KEY=
    BENCH_GEMINI_MODEL=
    BENCH_GEMMA_MODEL=gemma-4-26b-a4b-it
    GROQ_API_KEY=
    BENCH_GROQ_MODEL=

Para estimar custo, tambem podem ser informadas as tarifas atuais por milhao de tokens (entrada e saida por provedor):

    BENCH_GEMINI_INPUT_USD_PER_MILLION=
    BENCH_GEMINI_OUTPUT_USD_PER_MILLION=
    BENCH_GROQ_INPUT_USD_PER_MILLION=
    BENCH_GROQ_OUTPUT_USD_PER_MILLION=

Para executar uma repeticao do teste de ferramentas:

    python scripts/benchmark_chatbot/run_tools.py --repetitions 1

Para comecar com apenas um caso nos dois provedores:

    python scripts/benchmark_chatbot/run_tools.py --case estoque_savassi --repetitions 1

O argumento `--providers` pode limitar ou alterar os modelos. Por exemplo, `--providers gemini` executa somente Gemini; `--providers gemini gemma` compara os dois pela API do Google. Groq usa `GROQ_API_KEY`; Anthropic usa `ANTHROPIC_API_KEY`.

Para executar tres repeticoes do baseline:

    python scripts/benchmark_chatbot/run.py --repetitions 3

Cada execucao cria um CSV novo em `scripts/benchmark_chatbot/resultados/`, sem sobrescrever os anteriores. Os arquivos registram identificador e horario da rodada, provedor, modelo, caso, repeticao, verificacao automatica, latencia, tokens, chamadas de ferramentas, resposta, erros e estimativa de custo quando as tarifas estiverem configuradas. Assim, as rodadas podem ser reunidas depois para gerar graficos.

Os casos atuais usam fixtures ficticias. Nao use dados reais de clientes neste benchmark. A pontuacao automatica e heuristica; confira manualmente respostas e argumentos antes de comparar os modelos.
