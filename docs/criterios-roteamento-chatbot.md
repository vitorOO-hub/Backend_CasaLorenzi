# Criterios iniciais de roteamento do chatbot

## Objetivo

Direcionar perguntas simples para um modelo rapido e perguntas que exigem mais cuidado para um modelo com melhor desempenho. O classificador e heuristico e nao chama provedores.

## Dimensoes separadas

Complexidade da pergunta e necessidade de consultar dados sao avaliadas separadamente. Uma pergunta pode ser simples e ainda exigir uma ferramenta, por exemplo, consultar o estoque de um SKU especifico.

## Rotas

| Rota | Criterios | Exemplo |
| --- | --- | --- |
| `rapida` | Pergunta direta, de um passo, sem analise, ambiguidade ou dado pessoal/financeiro. Pode exigir uma ferramenta de leitura autorizada. | "Quantas unidades da CAM-001 temos na Savassi?" |
| `precisa` | Comparacao, explicacao, estimativa, raciocinio em varias etapas, multiplas perguntas, pontos/saldo pessoal, dados financeiros ou excecao de politica. Tentativa de obter ou inventar dado protegido tambem exige esta rota e as salvaguardas de seguranca. | "Compare as vendas dos meses e explique a diferenca." |
| `esclarecer` | Pergunta vazia ou falta identificar produto/pedido. Solicitar o dado que falta antes de chamar um modelo. | "Tem essa peca na loja?" |

## Quando usar ferramentas

Marcar `requer_ferramenta` quando a resposta depender de estoque, preco atual, pontos, pedido, horario ou indicadores do negocio. A classificacao nao executa a ferramenta nem autoriza acesso: autenticacao, autorizacao, escopo do usuario e validacao dos argumentos continuam obrigatorios no backend.

Se uma pergunta exige ferramenta e nenhum provedor/ferramenta compativel estiver disponivel, nao inventar a resposta. Pedir esclarecimento quando faltar dado ou informar que nao foi possivel consultar.

## Regras de seguranca

- Perguntas sobre pontos, compras, pedidos ou outros dados pessoais so podem consultar dados do proprio cliente autenticado, ou dados que o papel do funcionario esteja autorizado a ver.
- O modelo nunca decide permissao; o backend valida a sessao e o escopo antes da consulta.
- Perguntas ambiguas devem ser esclarecidas, nao adivinhadas.
- Excecoes de troca, estorno, pagamento ou politica devem ir para a rota `precisa`; a resposta deve se apoiar nas regras oficiais, sem inventar excecoes.
- Em duvida sobre a classificacao, usar `precisa` ou solicitar esclarecimento, nunca reduzir o nivel de cuidado.

## Estado do piloto

O mecanismo compartilhado esta em `app/assistente/roteamento.py`; o benchmark importa esse mesmo classificador. A decisao e heuristica, nao chama provedores e nao executa ferramentas. `requer_ferramenta` indica apenas que a resposta depende de dados atuais; autenticacao, autorizacao e escopo continuam no backend.

O destino de cada rota e configurado no servidor, nunca pela pergunta nem pelo usuario:

| Variavel | Exemplo de formato | Uso |
| --- | --- | --- |
| `ASSISTENTE_MODELO_RAPIDO` | `groq:openai/gpt-oss-20b` | perguntas diretas; modelo testado no benchmark |
| `ASSISTENTE_MODELO_PRECISO` | `gemini:gemini-3.5-flash-lite` | analise e dados sensiveis; modelo testado no benchmark |

Esses sao os destinos padrao e podem ser sobrescritos por variaveis de ambiente. Se a pergunta exigir esclarecimento, nenhum modelo e escolhido. Se faltar destino ou chave do provedor, o plano informa a indisponibilidade e nao faz fallback silencioso para uma rota de menor capacidade. O modulo ainda nao chama APIs; sera consumido pelo servico do chatbot.

Antes de integrar em producao, avaliar a classificacao com exemplos representativos e perguntas reais anonimizadas. Em caso de duvida, manter a rota `precisa` ou pedir esclarecimento.
