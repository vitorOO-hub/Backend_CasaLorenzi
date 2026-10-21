# clientes_vulto

Padroniza a planilha de clientes do programa de fidelidade Vulto+ (`clientes_fidelidade_FINAL_v3.xlsx`)
cruzando com o banco do sistema antigo (`vulto.db`), do mesmo jeito que a planilha
`clientes_fidelidade_final_padronizado.xlsx` foi feita à mão, e carrega o resultado no banco do
sistema novo (`usuario`, `movimento_pontos` e `resgate_pontos`). Precisa de Python 3.10 ou mais novo.

## Como usar

```bash
pip install -r requirements.txt

# gera a planilha padronizada (o vulto.db é aberto só para leitura)
python -m clientes_vulto limpar clientes_fidelidade_FINAL_v3.xlsx --banco vulto.db \
    --saida clientes_padronizado.xlsx --referencia 2026-10-19

# compara com a planilha padronizada à mão (mostra o que bate e exemplos do que não bate)
python conferir_com_planilha_padronizada.py clientes_fidelidade_FINAL_v3.xlsx vulto.db \
    clientes_fidelidade_final_padronizado.xlsx 2026-10-19

# gera as linhas da carga (CSV + relatório). NÃO grava no banco. Com DATABASE_URL definida,
# também confere o banco só lendo (lojas, CPF e e-mail já cadastrados) e põe no relatório.
python -m clientes_vulto carregar clientes_fidelidade_FINAL_v3.xlsx --banco vulto.db --saida-dir saida_carga

# grava no banco (uma transação: ou grava tudo ou nada). Pode ser repetido.
export DATABASE_URL="postgresql://usuario:senha@host:5432/banco"
python -m clientes_vulto carregar clientes_fidelidade_FINAL_v3.xlsx --banco vulto.db --saida-dir saida_carga --aplicar

# testes das regras
python -m pytest -q tests
```

Sempre confira `saida_carga/relatorio_carga.csv` antes de usar `--aplicar`. Na carga, `--referencia`
é o dia em que os pontos vencidos saem do saldo (padrão: hoje).

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
| Resgates: linhas | 579 de 580 |
| Resgates: todas as colunas | 100% |

O que não bate são casos isolados feitos à mão sem fonte nos dados (por exemplo, nomes abreviados
completados sem registro em lugar nenhum) ou que o conferidor lista um a um. Em Resgates, a final
manteve um resgate de "mariana" (batel, nov/2024) como "provável"; a mesma lógica atribuiria
também resgates que a final removeu, então o script remove esse e registra o aviso.

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
- **avisos**: o que precisa de alguém olhar (CPF sem correção, e-mail compartilhado sem dono claro,
  resgate removido por não identificar o cliente).

## Aba Resgates

| Campo | Regra |
|---|---|
| `data` | Mesmos formatos da aba Clientes; mês/ano ("jan/23") vira o **dia 1**, como está na planilha final |
| `cliente` | CPF (só números). Só com nome: o único cliente com esse nome (completo ou só o primeiro nome, sem acento); se houver vários, o único deles com compra na mesma loja no mesmo dia (±1), pelas compras e vendas do banco. Sem isso, o resgate é **removido** e entra nos avisos |
| `pontos usados`, `desconto R$` | Números (`'1.500'` → 1500; `'R$ 50,0'` → 50) |
| `loja` | Mesmos nomes da aba Clientes |
| `atendente` | Apelido → funcionário da loja do resgate (bia, rafa, cami, fer.batel, "patrícia w."...; a lista está em `resgates.APELIDOS`). "gerente" vira o gerente da loja. Apelido de dois funcionários da loja (rafa: rafael ou rafaela) desempata por quem registrou vendas na loja no dia. Sem certeza (outra loja, ou antes de 2025, quando não há vendas no banco), o apelido fica e a observação explica |
| `observacao` | Como o cliente e o atendente foram deduzidos e o desconto acima da regra (R$ 10 a cada 100 pontos até fev/2025; R$ 5 a cada 100 desde mar/2025). O desconto não é alterado, só anotado |

## Carga no banco

Antes da primeira carga, rode a migração `20261021150000` (`alembic upgrade head`, na pasta do backend).
Ela cria `usuario.origem_cadastro`, `usuario.aceita_mensagem` e `usuario.observacao`, deixa o e-mail
opcional para cliente (continua obrigatório para a equipe), deixa cliente importado do Vulto+ entrar sem
endereço, cria `movimento_pontos` e `resgate_pontos` e faz o cadastro pelo site assumir a conta importada
quando CPF e e-mail batem.

### public.usuario (um por CPF)

| Campo | Recebe |
|---|---|
| `documento` | cpf |
| `nome` | Nome; sem nome: `cliente vulto+ (nome a confirmar)` |
| `email` | E-mail; vazio quando não há ou quando já é de outra conta do sistema (fica no relatório) |
| `telefone` | Tel |
| `id_loja` | loja_cadastro procurada na tabela `loja` pelo nome: site = Vulto Ecommerce, app = Vulto App, pinheiros, eldorado, savassi e batel = a loja Vulto com esse nome. Sem loja: vazio |
| `criado_em` | Data Cadastro |
| `aceita_mensagem` | aceita_msg = sim |
| `observacao` | Obs |
| `origem_cadastro` | `vulto+` |
| `id_tipo_usuario` | cliente |

CPF que já pertence a uma conta que não veio do Vulto+ fica de fora (com os pontos) e vai para o
relatório, para decidir caso a caso. Na repetição, só é atualizado quem ainda não fez login.

### public.movimento_pontos (extrato)

Uma linha por evento: o saldo da planilha congelado em 01/01/2025 (`credito`), cada compra do banco
antigo com os pontos recalculados (`credito`), resgates (`resgate`), estornos e ajustes do banco antigo,
e o que fecha a conta na data de referência: `vencimento` de cada crédito não usado com 365 dias ou mais
e `ajuste` que perdoa resgate maior que o saldo. Cada crédito tem `vence_em` (365 dias). A soma do
extrato é o saldo da aba Clientes; a carga confere isso cliente a cliente antes de gravar.

### public.resgate_pontos

Cada linha da aba Resgates: `resgatado_em`, `pontos`, `desconto`, `id_loja` (mesma regra das lojas),
`atendente` e `observacao`.

### Cadastro pelo site

O cadastro exige CPF. Com o mesmo CPF e o mesmo e-mail de um cliente importado que
ainda não fez login, a conta nova é essa linha (com os pontos). CPF de outra conta barra o cadastro.
Cliente importado sem e-mail é ligado pelo atendimento.
