# catalogo_vulto

Limpa e padroniza a planilha de catálogo da Marina (as abas de coleção) e carrega nas tabelas
`public.produto` e `public.variacao_produto`.

## Como usar

```bash
pip install -r requirements.txt

# 1) só padronizar e conferir (gera um .xlsx com uma aba por coleção + Avisos)
python -m catalogo_vulto limpar planilha_original.xlsx --saida catalogo_padronizado.xlsx

# 2) gerar as linhas das duas tabelas (CSV + relatório). NÃO grava no banco.
python -m catalogo_vulto carregar planilha_original.xlsx --saida-dir saida_carga

# 3) gravar no banco (uma transação: ou grava tudo ou nada). Pode ser repetido.
export DATABASE_URL="postgresql://usuario:senha@host:5432/banco"
python -m catalogo_vulto carregar planilha_original.xlsx --saida-dir saida_carga --aplicar
```

Opções de `carregar`: `--marca "Vulto"` (padrão; escolhe a unidade do produto: `unidade.nome` = marca em minúsculas), `--incluir-antiga` (inclui a aba
PLANILHA ANTIGA NAO USAR; por padrão fica de fora).

Sempre confira `saida_carga/relatorio_carga.csv` antes de usar `--aplicar`.

## Em qual campo vai cada coisa

### public.variacao_produto (uma linha por SKU)

| Campo | Recebe |
|---|---|
| `sku` | SKU no formato completo `VLT-CAT-NNN-COR-TAM` (códigos reduzidos como `CAL001V36` e escritos por extenso como `vlt cal 001 verde oliva p` viram o completo) |
| `cor` | coluna COR padronizada (minúscula, 17 cores possíveis) |
| `tamanho` | coluna TAM em letras: 36 ou menos = PP, 38 = P, 40 = M, 42 e 44 = G, 46 = GG, único = U |
| `preco_venda` | PRECO, depois da regra do menor preço do modelo entre as coleções (ponto decimal) |
| `custo` | CUSTO da planilha (último custo, já com as regras de custo). Vazio quando a planilha não tem custo |
| `ean` | EAN da coleção que decidiu o SKU, como texto (não vira número, para não perder zeros nem virar notação científica). Vazio quando está em branco |
| `ativa` | `false` se a linha estava tachada ou em vermelho (X = descontinuada); `true` nas demais |
| `id_produto` | id do produto do modelo (CAT-NNN) a que o SKU pertence |
| `id_variacao`, `criada_em`, `atualizada_em` | valores padrão do banco |

### public.produto (uma linha por modelo, o `CAT-NNN` do SKU)

| Campo | Recebe |
|---|---|
| `nome` | coluna PRODUTO (minúscula), da coleção mais nova em que o modelo aparece |
| `categoria` | coluna CATEGORIA padronizada (singular, minúscula, sem subcategoria) |
| `colecao` | nome da coleção da planilha (nome da aba, minúscula, ex.: `verão 26`). Modelo em mais de uma coleção recebe todas, da mais antiga para a mais nova, separadas por vírgula, ex.: `inverno 25, inverno 26` |
| `preco_base` | menor `preco_venda` entre as variações ativas do modelo |
| `ativo` | `true` se o modelo tem pelo menos uma variação ativa |
| `cores` | lista JSON das cores das variações, ex.: `["bege","preto"]` |
| `id_unidade` | unidade com o nome da marca em minúsculas (`vulto`, a planilha não tem marca; troque com `--marca`); só preenche se estiver vazio |
| `imagem_url`, `imagem_alt`, `imagem_vestida_url`, `tipo`, `tecido`, `tecelagem`, `costurado_em`, `nota` | vazios (não existem na planilha) |
| `id_produto`, `criado_em`, `atualizado_em` | id gerado a partir do modelo (o mesmo modelo sempre gera o mesmo id); datas pelo padrão do banco |

### Sem coluna nas duas tabelas

Só a OBS (observação da planilha) não tem coluna. Sai em `saida_carga/campos_sem_tabela.csv` (uma linha por SKU).

## Antes da primeira carga: rodar a migração

A migração é a revisão alembic `20261019120000` (`alembic upgrade head`, na pasta do backend). Ela cria
`variacao_produto.custo` (`numeric(12,2)`, aceita vazio) e `variacao_produto.ean` (`text`, aceita vazio), cria o índice
único parcial `uq_variacao_produto_ean` (EAN único entre as variações que têm EAN) e renomeia `produto.descricao`
para `produto.colecao`.

O EAN é **único**: EAN repetido na planilha (ex.: `7890000000000` em 7 SKUs) é gravado vazio e fica no
`relatorio_carga.csv` ("EAN repetido em mais de um SKU"). Outros avisos de EAN: "EAN diferente entre coleções", "sem EAN",
"EAN inválido".

## Regras de padronização aplicadas

SKU `VLT-CAT-NNN-COR-TAM`; tamanho numérico vira letra; grades ("36/38/40") viram uma linha por tamanho;
categoria no singular, sem subcategoria, e o nome do produto decide quando havia duas opções; cor em
minúscula, grafias muito parecidas unificadas, inglês traduzido, tons diferentes (bege/areia) mantidos;
preço e custo com vírgula na planilha de conferência; DESCONTINUADA = X para tachado ou vermelho;
COLEÇÃO = nome da aba em minúscula; custo pelo último custo (mesmo SKU, da aba mais nova para a mais antiga,
e custo em branco usa o mesmo produto na própria aba); preço pelo menor preço do modelo entre as coleções
(aba antiga e linhas X ficam fora dessa regra).

## O que o código decide para respeitar as restrições do banco

- **SKU único:** o mesmo SKU em várias coleções vira uma única variação. A coleção mais nova decide cor,
  tamanho e preço. Se o SKU está ativo em uma coleção e como X em outra, a linha X é descartada (X significa
  que o SKU pode ser reaproveitado). Cada caso fica no relatório.
- **42 e 44 viram o mesmo G**, então só uma variação (SKU e grade únicos). Cada caso fica no relatório
  ("tamanhos no mesmo SKU"). Esta é uma decisão que ainda está em aberto.
- **Aba antiga fora**, a menos que use `--incluir-antiga`.
- **Linhas sem preço** não são carregadas (`preco_venda` é obrigatório) e aparecem no relatório.
- **Valores sem regra** (cor nova, categoria nova, tamanho estranho, código inválido) não derrubam a execução:
  a linha é ignorada e vai para os avisos. Não há regra inventada para eles.
- **Aba nova** (ex.: "Verão 27") é tratada como a coleção mais nova, com aviso.
- **Repetir a carga é seguro:** os produtos são encontrados pelos SKUs que já existem; preço, categoria,
  `ativo` e `ativa` são atualizados. `cores` só é preenchido se estiver vazio. Imagem e demais campos que você
  preencher à mão não são tocados.

## Testes

```bash
python -m pytest -q tests
python conferir_com_planilha_padronizada.py planilha_original.xlsx catalogo_PADRONIZADO_v14.xlsx
```
O segundo comando compara a saída do código com o v14 conferido, célula a célula.
