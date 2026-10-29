// Uma mensagem por loja com estoque parado. Loja sem peca parada nao recebe e-mail.
const config = $('Configuração').first().json;
const dados = $input.first().json;

const esc = (t) => String(t ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
const reais = (v) => Number(v).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
const data = (iso) => (iso ? new Date(iso).toLocaleDateString('pt-BR', { timeZone: 'America/Sao_Paulo' }) : 'nunca vendeu');
const td = 'style="padding:6px 8px;border-bottom:1px solid #dfd9cf;vertical-align:top"';
const th = 'style="padding:6px 8px;text-align:left;border-bottom:2px solid #1f2a48;font-size:12px;color:#5e6b89"';

const saida = [];
for (const loja of dados.lojas) {
  if (!loja.total_itens) continue;
  const linhas = loja.itens
    .map((p) => `<tr><td ${td}>${esc(p.produto)} · ${esc(p.cor)}, ${esc(p.tamanho)} <span style="color:#5e6b89">(${esc(p.sku)})</span></td>
<td ${td}>${p.saldo}</td><td ${td}>${reais(p.valor_parado)}</td><td ${td}>${data(p.ultima_venda)}</td></tr>`)
    .join('\n');
  const mostrando = loja.itens.length < loja.total_itens ? `<p style="font-size:12px;color:#5e6b89">Mostrando as ${loja.itens.length} de maior valor parado.</p>` : '';
  const html = `<div style="font-family:Arial,sans-serif;color:#16203a;max-width:720px">
<p style="font-size:12px;letter-spacing:.16em;text-transform:uppercase;color:#b46746;margin:0">Casa Lorenzi · Estoque parado</p>
<h2 style="font-family:Georgia,serif;font-weight:normal;color:#1f2a48;margin:4px 0 12px">${esc(loja.loja)}</h2>
<p>${loja.total_itens} ${loja.total_itens === 1 ? 'peça' : 'peças'} (${loja.total_unidades} unidades, ${reais(loja.total_valor)}) sem venda há mais de ${dados.dias} dias.
Avalie transferir para outra loja ou sugerir uma ação de venda.</p>
<table style="border-collapse:collapse;width:100%;font-size:14px"><tr><th ${th}>Peça</th><th ${th}>Saldo</th><th ${th}>Valor parado</th><th ${th}>Última venda</th></tr>
${linhas}</table>${mostrando}
<p style="margin-top:24px"><a href="${esc(config.painel_url)}" style="color:#1f2a48">Abrir o painel de estoque</a></p>
<p style="font-size:12px;color:#5e6b89">${esc(dados.criterio)}</p></div>`;
  saida.push({
    json: {
      id_loja: loja.id_loja,
      loja: loja.loja,
      para: config.destinatarios,
      assunto: `Estoque parado · ${loja.loja}: ${loja.total_itens} ${loja.total_itens === 1 ? 'peça' : 'peças'} sem venda há ${dados.dias}+ dias`,
      html,
    },
  });
}
return saida;
