const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const root = path.resolve(__dirname, '..');

function montarItem(arquivo, relatorio) {
  const codigo = fs.readFileSync(path.join(root, 'n8n', arquivo), 'utf8');
  return new Function('$json', codigo)(relatorio);
}

function montarEmail(arquivo, relatorio) {
  return montarItem(arquivo, relatorio).json.html;
}

const estoque = {
  total_itens: 393,
  total_unidades: 1039,
  total_valor: 12345,
  itens: Array.from({length: 10}, (_, index) => ({
    produto: `Produto ${index + 1}`,
    cor: 'Preto',
    tamanho: 'M',
    sku: `SKU-${index + 1}`,
    loja: 'Casa Lorenzi Centro',
    saldo: index + 1,
    valor_parado: 100,
    ultima_venda: null,
  })),
};

const relatorioBase = {
  destinatarios: ['gestor@exemplo.com'],
  semana: {inicio: '2026-10-19', fim: '2026-10-25'},
  semana_anterior: {inicio: '2026-10-12', fim: '2026-10-18'},
  criterio_vendas: 'Vendas pagas.',
  faturamento: 1000,
  faturamento_anterior: 900,
  lojas: [{
    loja: 'Casa Lorenzi Centro',
    faturamento: 1000,
    pedidos: 10,
    faturamento_online: 100,
    faturamento_anterior: 900,
    pedidos_anterior: 9,
    variacao: 0.1,
  }],
  estoque_parado: estoque,
  indicadores_unidade: {
    ticket_medio: 100,
    pecas_vendidas: 18,
    categorias_mais_vendidas: [
      {categoria: 'Camisas', unidades: 10, faturamento: 800},
      {categoria: 'Calças', unidades: 8, faturamento: 650},
    ],
  },
  pontos_a_vencer: null,
};

for (const [perfil, arquivo] of [
  ['admin', 'codigo_email_relatorio_admin.js'],
  ['gerente', 'codigo_email_relatorio_gerente.js'],
]) {
  test(`e-mail ${perfil} explica totais e itens de estoque não exibidos`, () => {
    const html = montarEmail(arquivo, relatorioBase);

    assert.match(html, /393 variações sem venda nos últimos 60 dias · 1\.039 unidades no total/);
    assert.match(html, /A lista mostra 10 variações com maior valor parado, somando 55 unidades\./);
    assert.match(html, /383 outras variações \(984 unidades\) não aparecem na lista\./);
    assert.match(html, />Unidades na variação</);
  });
}

test('e-mail do gerente inclui ticket médio, peças e ranking por categoria', () => {
  const html = montarEmail('codigo_email_relatorio_gerente.js', relatorioBase);

  assert.match(html, />R\$\s?100,00</);
  assert.match(html, />18</);
  assert.match(html, /Categorias mais vendidas · por unidades/);
  assert.match(html, /Camisas/);
  assert.match(html, /Calças/);
});

test('e-mail do admin não recebe os indicadores exclusivos da unidade', () => {
  const html = montarEmail('codigo_email_relatorio_admin.js', relatorioBase);

  assert.doesNotMatch(html, /Categorias mais vendidas · por unidades/);
  assert.doesNotMatch(html, /TICKET MÉDIO/);
});

test('o destinatário vem do cadastro e, sem ele, o e-mail não sai', () => {
  const dois = {...relatorioBase, destinatarios: ['a@exemplo.com', 'b@exemplo.com']};
  assert.equal(montarItem('codigo_email_relatorio_admin.js', dois).json.para, 'a@exemplo.com,b@exemplo.com');

  const sem = {...relatorioBase, destinatarios: []};
  assert.equal(montarItem('codigo_email_relatorio_admin.js', sem), null);
});
