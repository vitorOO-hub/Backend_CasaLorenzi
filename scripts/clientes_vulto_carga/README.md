# clientes_vulto

Padroniza a planilha de clientes do programa de fidelidade Vulto+ (`clientes_fidelidade_FINAL_v3.xlsx`)
cruzando com o banco do sistema antigo (`vulto.db`), do mesmo jeito que a planilha
`clientes_fidelidade_final_padronizado.xlsx` foi feita à mão.

## Como usar

```bash
pip install -r requirements.txt

# gera a planilha padronizada (o vulto.db é aberto só para leitura)
python -m clientes_vulto limpar clientes_fidelidade_FINAL_v3.xlsx --banco vulto.db \
    --saida clientes_padronizado.xlsx --referencia 2026-10-19

# compara com a planilha padronizada à mão (mostra o que bate e exemplos do que não bate)
python conferir_com_planilha_padronizada.py clientes_fidelidade_FINAL_v3.xlsx vulto.db \
    clientes_fidelidade_final_padronizado.xlsx 2026-10-19

# testes das regras
python -m pytest -q tests
```

`--referencia` é o dia em que os pontos são contados e vencidos (padrão: hoje). Para reproduzir a
planilha final, use `2026-10-19`, o dia em que ela foi feita.

As planilhas e o `vulto.db` têm dados pessoais: **não os coloque no repositório**.

## O que bate com a planilha final (referência 19/10/2026)

| Aba / coluna | Igual à final |
|---|---|
| Clientes: linhas | 2.928 de 2.928 |
| Clientes: aceita_msg | 100% |
| Clientes: Data Cadastro, E-mail, loja_cadastro, Nome | 99,7% a 99,9% |
| Clientes: Tel, categoria | 99,6% |
| Clientes: Obs | 98,6% |
| Clientes: Pontos | 95,7% |
| clientes antigos, LEIA ISSO | 100% |
| Resgates | **ainda não tratada** (vai como está; ver abaixo) |

O que não bate são casos isolados feitos à mão sem fonte nos dados (por exemplo, nomes abreviados
completados sem registro em lugar nenhum) ou que o conferidor lista um a um.

## Regras da aba Clientes

| Campo | Regra |
|---|---|
| `cpf` | Só números; 9 ou 10 dígitos recebem os zeros que o Excel cortou. CPF inválido com **um dígito errado** é corrigido quando o CPF certo aparece no banco ou na aba Resgates. Sem correção, a conta é removida (não existe conta sem CPF) e entra nos avisos |
| contas duplicadas | Uma linha por CPF: vale o primeiro valor preenchido; **os pontos das contas são somados**; e-mails diferentes viram "e-mail alternativo" na Obs |
| `Nome` | Minúsculas, sem espaços repetidos. Nome abreviado ("joão b. teixeira") só é completado quando há fonte nos dados: outra linha do mesmo CPF ou a aba clientes antigos |
| `E-mail` | Minúsculas; "-" e "nao tem" ficam vazios; corrige `gmial.com`, `hotmail.con`, `uol.con.br`. E-mail usado por mais de um CPF fica com quem tem o primeiro nome igual ao início do e-mail; o outro perde o e-mail e recebe nota na Obs |
| `Tel` | Só números, sem +55. Sem DDD: usa o DDD da loja física de cadastro (Pinheiros e Eldorado 11, Savassi 31, Batel 41); no site/app, o DDD da loja física onde o cliente mais comprou, ou o telefone completo de uma compra dele. Se não houver, fica sem DDD e a Obs pede ao cliente |
| `Data Cadastro` | `AAAA-MM-DDT00:00:00-03:00`. Aceita data do Excel, número de série, `DD/MM/AAAA`, `AAAA-MM-DD`; mês/ano ("jun/21") vira o **dia 16** (média dos dias) |
| `aceita_msg` | `sim` só com S, 1 ou sim; "x", vazio, N, 0 viram `não`. "não ligar" na Obs força `não` (LGPD) |
| `loja_cadastro` | Nomes unificados: ecommerce → site, eldorado shop → eldorado, bh → savassi, cwb → batel |
| `Obs` | Minúsculas. Anotações vagas sem ação ("trocou de cpf?", "ver com gerente", "cliente reclamou", "cadastro refeito", "vip") são descartadas; as demais ficam, seguidas das notas do tratamento |
| `Pontos` | Ver abaixo |
| `categoria` | Recalculada pela regra do programa sobre os pontos creditados no ano da referência: bronze até 1.999, prata 2.000–4.999, ouro 5.000+ |

### Pontos

1. O saldo da coluna Pontos foi congelado em 01/01/2025: entra como crédito nessa data.
2. Depois disso valem as movimentações do banco. Créditos de compra são **recalculados**: R$ 1 = 1
   ponto, site e app em dobro, arredondando depois de multiplicar. O app às vezes gravou centavos
   (`25990` = R$ 259,90); os ajustes "correcao bug app" que desfaziam esse erro são ignorados, porque o
   crédito já sai certo.
3. Compras canceladas, aguardando, estornadas ou com chargeback não dão pontos (e o estorno delas no
   banco é ignorado, para não descontar duas vezes).
4. Compras lançadas com telefone ou e-mail em vez de CPF são ligadas ao cliente (e-mail ou últimos 9
   dígitos do telefone) e creditadas. A mesma compra lançada duas vezes (mesmo valor, loja e dia)
   conta uma vez.
5. Resgates consomem primeiro os pontos mais antigos. Na data de referência, vence o que foi
   creditado há 365 dias ou mais e não foi usado. O saldo nunca fica negativo.

### Clientes que entram na aba

- **Só no banco** (têm movimentação mas não estão na planilha): entram sem nome, com os pontos do banco
  e a Obs "nome não informado: pedir ao cliente".
- **Aba clientes antigos**, status ATIVO e fora da aba Clientes: entram com 0 pontos (os de 2023
  venceram) e a Obs com os pontos de 2023 e a última compra.

## Outras abas

- **clientes antigos**: mesmas padronizações; STATUS vazio vira `ativo` se o cliente está na aba
  Clientes ou tem movimentação no banco, senão `inativo`, com a explicação na coluna `obs`.
- **LEIA ISSO**: o texto em minúsculas.
- **resumo categorias**: contagem e porcentagem por categoria (substitui a antiga Plan1).
- **avisos**: o que precisa de alguém olhar (CPF sem correção, e-mail compartilhado sem dono claro).
- **Resgates**: pendente. A planilha final deduziu cliente e atendente por nome e por vendas do dia e
  removeu resgates sem cliente identificável; essas regras aguardam decisão do time.
