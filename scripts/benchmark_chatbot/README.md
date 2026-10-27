# Benchmark isolado do chatbot

Este piloto compara Gemini e Groq por padrao, com as mesmas perguntas e fixtures inteiramente ficticias. Anthropic continua disponivel como opcao explicita, mas nao faz parte da comparacao atual. O benchmark nao acessa o banco, nao chama endpoints da plataforma e nao altera o deploy.

As chaves e modelos serao configurados depois no `.env` local. O resultado sera salvo fora do repositorio. Nenhum dos scripts acessa banco, endpoints da plataforma ou deploy.

## Modos de teste

- `run.py`: baseline com contexto ficticio no prompt, sem chamar ferramentas.
- `run_tools.py`: envia definicoes de ferramentas simuladas para medir se o modelo escolhe a funcao e os argumentos esperados, alem de avaliar a resposta final. Todas as respostas das funcoes sao fixtures locais ficticias.

O segundo modo pode fazer mais de uma requisicao por caso (uma para solicitar a ferramenta e outra para responder com o resultado). Comece com uma repeticao; os custos de API, caso as chaves estejam configuradas, sao reais. As estimativas de custo so aparecem se as tarifas por milhao de tokens forem preenchidas e nao incluem eventuais diferencas de cobranca entre modelos.

Para a comparacao atual, configure no `.env` local. A Groq tem limites de uso no plano gratuito; nao faca upgrade para o plano Developer se a ideia e evitar cobrancas.

    GEMINI_API_KEY=
    GROQ_API_KEY=
    BENCH_GEMINI_MODEL=
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

O argumento `--providers` pode limitar ou alterar os provedores. Por exemplo, `--providers gemini groq` e o padrao atual; incluir `anthropic` so deve ser feito se decidirem testa-lo e configurarem sua chave.

Para executar tres repeticoes do baseline:

    python scripts/benchmark_chatbot/run.py --repetitions 3

Cada execucao cria um CSV novo em `scripts/benchmark_chatbot/resultados/`, sem sobrescrever os anteriores. Os arquivos registram identificador e horario da rodada, provedor, modelo, caso, repeticao, verificacao automatica, latencia, tokens, chamadas de ferramentas, resposta, erros e estimativa de custo quando as tarifas estiverem configuradas. Assim, as rodadas podem ser reunidas depois para gerar graficos.

Os casos atuais usam fixtures ficticias. Nao use dados reais de clientes neste benchmark. A pontuacao automatica e heuristica; confira manualmente respostas e argumentos antes de comparar os modelos.
