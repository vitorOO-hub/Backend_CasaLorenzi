// Monta uma mensagem por loja com pendencias. Loja sem nada a resolver nao recebe e-mail.
const config = $('Configuração').first().json;
const dados = $input.first().json;

const esc = (t) => String(t ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
const data = (iso) => (iso ? new Date(iso).toLocaleDateString('pt-BR', { timeZone: 'America/Sao_Paulo' }) : '-');
const peca = (p) => `${esc(p.produto)} · ${esc(p.cor)}, ${esc(p.tamanho)} <span style="color:#5e6b89">(${esc(p.sku)})</span>`;
const hoje = new Date().toLocaleDateString('pt-BR', { timeZone: 'America/Sao_Paulo' });

const td = 'style="padding:6px 8px;border-bottom:1px solid #dfd9cf;vertical-align:top"';
const th = 'style="padding:6px 8px;text-align:left;border-bottom:2px solid #1f2a48;font-size:12px;color:#5e6b89"';
const tabela = (titulo, colunas, linhas) =>
  linhas.length === 0
    ? ''
    : `<h3 style="font-family:Georgia,serif;font-weight:normal;color:#1f2a48;margin:24px 0 8px">${titulo} (${linhas.length})</h3>
<table style="border-collapse:collapse;width:100%;font-size:14px"><tr>${colunas.map((c) => `<th ${th}>${c}</th>`).join('')}</tr>
${linhas.map((l) => `<tr>${l.map((c) => `<td ${td}>${c}</td>`).join('')}</tr>`).join('\n')}</table>`;

const saida = [];
for (const loja of dados.lojas) {
  if (!loja.tem_pendencias) continue;
  const sobra = (p) =>
    p.lojas_com_sobra.length ? p.lojas_com_sobra.map((s) => `${esc(s.loja)} (+${s.sobra})`).join('<br>') : 'nenhuma loja';
  const transf = (t, com) => [peca(t), t.quantidade, esc(com(t)), data(t.solicitada_em)];
  const corpo = [
    tabela('Abaixo do mínimo', ['Peça', 'Saldo', 'Mínimo', 'Pedir para'],
      loja.abaixo_do_minimo.map((p) => [peca(p), p.saldo, p.minimo, sobra(p)])),
    tabela('Pedidos de outras lojas para responder', ['Peça', 'Qtd.', 'Quem pediu', 'Pedido em'],
      loja.para_responder.map((t) => transf(t, (x) => x.destino))),
    tabela('Seus pedidos ainda sem resposta', ['Peça', 'Qtd.', 'Pedido a', 'Pedido em'],
      loja.pedidos_sem_resposta.map((t) => transf(t, (x) => x.origem ?? 'rede (qualquer loja)'))),
    tabela('Em trânsito: confirme o recebimento', ['Peça', 'Qtd.', 'Vem de', 'Aceita em'],
      loja.a_receber.map((t) => [peca(t), t.quantidade, esc(t.origem ?? 'rede'), data(t.aceita_em)])),
    tabela('Ajustes de inventário aguardando aprovação', ['Peça', 'Qtd.', 'Motivo', 'Pedido por'],
      loja.ajustes_pendentes.map((a) => [peca(a), a.quantidade > 0 ? `+${a.quantidade}` : a.quantidade, esc(a.motivo), `${esc(a.solicitante)}, ${data(a.solicitado_em)}`])),
  ].join('\n');
  const criterios = Object.values(dados.criterios).map((c) => `<li>${esc(c)}</li>`).join('');
  const html = `<div style="font-family:Arial,sans-serif;color:#16203a;max-width:720px">
<p style="font-size:12px;letter-spacing:.16em;text-transform:uppercase;color:#b46746;margin:0">Casa Lorenzi · Estoque</p>
<h2 style="font-family:Georgia,serif;font-weight:normal;color:#1f2a48;margin:4px 0 0">${esc(loja.loja)} — ${hoje}</h2>
${corpo}
<p style="margin-top:24px"><a href="${esc(config.painel_url)}" style="color:#1f2a48">Abrir o painel de estoque</a></p>
<ul style="font-size:12px;color:#5e6b89;padding-left:16px">${criterios}</ul></div>`;
  const total =
    loja.abaixo_do_minimo.length + loja.para_responder.length + loja.pedidos_sem_resposta.length +
    loja.a_receber.length + loja.ajustes_pendentes.length;
  saida.push({
    json: {
      id_loja: loja.id_loja,
      loja: loja.loja,
      para: config.destinatarios,
      assunto: `Estoque do dia · ${loja.loja}: ${total} ${total === 1 ? 'item' : 'itens'} para resolver`,
      html,
    },
  });
}
return saida;
