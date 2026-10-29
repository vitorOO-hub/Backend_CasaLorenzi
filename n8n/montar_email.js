// Nó "Montar e-mail" do fluxo "Casa Lorenzi - e-mails ao cliente" (n8n, nó Code, modo "Run Once for
// Each Item"). Recebe o corpo do webhook que o backend manda (app/automacoes/emails.py) e devolve
// { para, assunto, html, texto }. Os textos que vêm do banco (nome, produtos) são escapados.
// Mudou este arquivo? Cole de novo no nó Code do n8n (ou reimporte n8n/fluxo_emails.json).

const corpo = $json.body ?? $json;

const COR = {
  fundo: "#f6f3ee", papel: "#ffffff", tinta: "#16203a", suave: "#5e6b89",
  marinho: "#1f2a48", dourado: "#b46746", douradoClaro: "#f5e6dc", linha: "#dfd9cf",
};

const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const moeda = (v) => Number(v || 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
const inteiro = (v) => Number(v || 0).toLocaleString("pt-BR");
const dia = (iso) => {
  const d = new Date(iso);
  return isNaN(d) ? esc(iso) : d.toLocaleDateString("pt-BR", { timeZone: "America/Sao_Paulo" });
};
const pontosTxt = (n) => `${inteiro(n)} ${Number(n) === 1 ? "ponto" : "pontos"}`;

if (!corpo || !corpo.tipo || !corpo.para || !corpo.para.email) {
  throw new Error("Corpo inválido: faltam tipo ou para.email");
}

const nome = esc(corpo.para.primeiro_nome || "cliente");
const site = String(corpo.site || "https://projetocasalorenzi.vercel.app").replace(/\/$/, "");

function moldura(titulo, conteudo, botao) {
  const cta = botao
    ? `<tr><td style="padding:8px 32px 32px"><a href="${esc(botao.link)}" style="display:inline-block;background:${COR.marinho};color:#fff;text-decoration:none;padding:12px 22px;border-radius:4px;font-size:14px">${esc(botao.texto)}</a></td></tr>`
    : "";
  return `<!doctype html><html lang="pt-BR"><body style="margin:0;background:${COR.fundo};font-family:Arial,Helvetica,sans-serif;color:${COR.tinta}">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:${COR.fundo};padding:24px 12px"><tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background:${COR.papel};border:1px solid ${COR.linha}">
<tr><td style="background:${COR.marinho};padding:20px 32px;color:#fff;font-family:Georgia,serif;font-size:22px;letter-spacing:.5px">Casa Lorenzi</td></tr>
<tr><td style="padding:28px 32px 8px;font-family:Georgia,serif;font-size:24px;line-height:1.25">${titulo}</td></tr>
<tr><td style="padding:8px 32px 16px;font-size:15px;line-height:1.6">${conteudo}</td></tr>
${cta}
<tr><td style="padding:16px 32px;border-top:1px solid ${COR.linha};font-size:12px;color:${COR.suave}">Você recebeu este e-mail porque é cliente da Casa Lorenzi e participa do Lorenzi+. Dúvidas? Responda este e-mail ou fale com a sua loja.</td></tr>
</table></td></tr></table></body></html>`;
}

function blocoBeneficios(proxima) {
  if (!proxima) return "";
  const lista = (proxima.beneficios || [])
    .map((b) => `<li style="margin:4px 0"><strong>${esc(b.titulo)}</strong>: ${esc(b.descricao)}</li>`)
    .join("");
  return `<div style="background:${COR.douradoClaro};border-left:3px solid ${COR.dourado};padding:14px 16px;margin:16px 0">
<p style="margin:0 0 6px">Faltam <strong>${pontosTxt(proxima.faltam)}</strong> para você chegar à categoria <strong>${esc(proxima.nome)}</strong>.</p>
${lista ? `<p style="margin:8px 0 4px">No ${esc(proxima.nome)} você ganha:</p><ul style="margin:0;padding-left:18px">${lista}</ul>` : ""}
</div>`;
}

let assunto, html, texto;

if (corpo.tipo === "pos_compra") {
  const p = corpo.pedido;
  const linhas = (p.itens || [])
    .map((i) => `<tr><td style="padding:8px 0;border-bottom:1px solid ${COR.linha}">${esc(i.produto)}<br><span style="color:${COR.suave};font-size:13px">${inteiro(i.quantidade)} × ${moeda(i.preco_unitario)}</span></td><td align="right" style="padding:8px 0;border-bottom:1px solid ${COR.linha};white-space:nowrap">${moeda(i.total)}</td></tr>`)
    .join("");
  const frete = Number(p.frete) > 0 ? `<tr><td style="padding:6px 0">Frete</td><td align="right">${moeda(p.frete)}</td></tr>` : "";
  const pontos = corpo.pontos && Number(corpo.pontos.ganhos) > 0
    ? `<p style="margin:16px 0 0">Você ganhou <strong>${pontosTxt(corpo.pontos.ganhos)}</strong> Lorenzi+ nesta compra. Seu saldo agora é de ${pontosTxt(corpo.pontos.saldo)}.</p>`
    : "";
  assunto = `Obrigado pela sua compra, ${corpo.para.primeiro_nome || "cliente"}! Pedido ${p.numero}`;
  html = moldura(
    `Obrigado pela sua compra, ${nome}!`,
    `<p style="margin:0 0 12px">Este é o resumo da sua compra na <strong>${esc(p.loja)}</strong> em ${dia(p.data)}.</p>
<p style="margin:0 0 12px;color:${COR.suave};font-size:13px">Pedido <strong style="color:${COR.tinta}">${esc(p.numero)}</strong>${p.pagamento ? ` · Pagamento: ${esc(p.pagamento)}` : ""}</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="font-size:14px">${linhas}${frete}
<tr><td style="padding:10px 0;font-weight:bold">Total</td><td align="right" style="padding:10px 0;font-weight:bold">${moeda(p.total)}</td></tr></table>
${pontos}
<p style="margin:16px 0 0;font-size:12px;color:${COR.suave}">Este e-mail é um resumo da compra e não substitui a nota fiscal.</p>`,
    { texto: "Ver minhas compras", link: `${site}/conta/pedidos` },
  );
  texto = `Obrigado pela sua compra! Pedido ${p.numero}, total ${moeda(p.total)}.`;
} else if (corpo.tipo === "pontos") {
  const pt = corpo.pontos;
  const venc = (pt.vencimentos || [])
    .map((v) => `<li style="margin:4px 0"><strong>${pontosTxt(v.pontos)}</strong> vencem em ${dia(v.data)}</li>`)
    .join("");
  const primeira = (pt.vencimentos || [])[0];
  assunto = `${corpo.para.primeiro_nome || "Olá"}, ${pontosTxt(pt.a_vencer)} Lorenzi+ vencem ${primeira ? `em ${dia(primeira.data)}` : "em breve"}`;
  html = moldura(
    `Seus pontos estão perto de vencer, ${nome}`,
    `<p style="margin:0 0 8px">Você tem <strong>${pontosTxt(pt.a_vencer)}</strong> Lorenzi+ que vencem nos próximos dias:</p>
<ul style="margin:0 0 12px;padding-left:18px">${venc}</ul>
<p style="margin:0">Seu saldo total é de <strong>${pontosTxt(pt.saldo)}</strong>. Use seus pontos como desconto na próxima compra, no site ou em qualquer uma das nossas casas, antes que eles vençam.</p>
${blocoBeneficios(corpo.categoria && corpo.categoria.proxima)}`,
    { texto: "Ver meus pontos", link: `${site}/conta/lorenzi-mais` },
  );
  texto = `Você tem ${pontosTxt(pt.a_vencer)} Lorenzi+ vencendo. Saldo: ${pontosTxt(pt.saldo)}.`;
} else if (corpo.tipo === "categoria") {
  const prox = corpo.categoria && corpo.categoria.proxima;
  if (!prox) throw new Error("Aviso de categoria sem próxima categoria");
  assunto = `${corpo.para.primeiro_nome || "Olá"}, faltam ${pontosTxt(prox.faltam)} para o ${prox.nome}`;
  html = moldura(
    `Você está quase no ${esc(prox.nome)}, ${nome}!`,
    `<p style="margin:0 0 8px">Hoje você é cliente <strong>${esc(corpo.categoria.atual.nome)}</strong> do Lorenzi+ e está muito perto da próxima categoria.</p>
${blocoBeneficios(prox)}
<p style="margin:0">Cada compra soma pontos. Você tem ${pontosTxt(corpo.pontos.saldo)} hoje.</p>`,
    { texto: "Ver meu Lorenzi+", link: `${site}/conta/lorenzi-mais` },
  );
  texto = `Faltam ${pontosTxt(prox.faltam)} para a categoria ${prox.nome} do Lorenzi+.`;
} else {
  throw new Error(`Tipo de e-mail desconhecido: ${corpo.tipo}`);
}

return { json: { para: corpo.para.email, assunto, html, texto, tipo: corpo.tipo } };
