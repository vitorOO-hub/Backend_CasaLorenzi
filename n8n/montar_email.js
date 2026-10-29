// Nó "Montar e-mail" do fluxo "Casa Lorenzi - e-mails ao cliente" (n8n, nó Code, modo "Run Once for
// Each Item"). Recebe o corpo do webhook que o backend manda (app/automacoes/emails.py) e devolve
// { para, assunto, html, texto }. Os textos que vêm do banco (nome, produtos, loja) são escapados.
// HTML de e-mail: só tabelas e estilo inline (Gmail, Outlook e celular).
// Mudou este arquivo? Cole de novo no nó Code do n8n (ou reimporte n8n/fluxo_emails.json).

const corpo = $json.body ?? $json;

const COR = {
  fundo: "#f6f3ee", papel: "#ffffff", tinta: "#16203a", suave: "#5e6b89", linha: "#e7e1d7",
  marinho: "#1f2a48", dourado: "#b46746", douradoClaro: "#f8ece4", vinho: "#7a1020", areia: "#eeeae3",
};
const SERIFA = "Georgia,'Times New Roman',serif";
const SANS = "'Helvetica Neue',Helvetica,Arial,sans-serif";

const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const MINUSCULAS = new Set(["de", "da", "do", "das", "dos", "e", "em", "com"]);
// O banco guarda nomes em minúsculas ("calça alfaiataria torino"): no e-mail, cada palavra com maiúscula.
const titulo = (v) => String(v ?? "").trim().split(/\s+/).map((p, i) => {
  if (i > 0 && MINUSCULAS.has(p.toLowerCase())) return p.toLowerCase();
  if (/^[A-Z0-9]{1,3}$/.test(p)) return p; // tamanhos (PP, GG, 42) e siglas ficam como estão
  return p.charAt(0).toUpperCase() + p.slice(1).toLowerCase();
}).join(" ");
const moeda = (v) => Number(v || 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
const inteiro = (v) => Number(v || 0).toLocaleString("pt-BR");
const dataLonga = (iso) => {
  const d = new Date(iso);
  return isNaN(d) ? esc(iso) : d.toLocaleDateString("pt-BR", { timeZone: "America/Sao_Paulo", day: "numeric", month: "long", year: "numeric" });
};
const dataCurta = (iso) => {
  const d = new Date(iso);
  return isNaN(d) ? esc(iso) : d.toLocaleDateString("pt-BR", { timeZone: "America/Sao_Paulo", day: "2-digit", month: "2-digit" });
};
const pontosTxt = (n) => `${inteiro(n)} ${Number(n) === 1 ? "ponto" : "pontos"}`;

if (!corpo || !corpo.tipo || !corpo.para || !corpo.para.email) {
  throw new Error("Corpo inválido: faltam tipo ou para.email");
}

const primeiro = titulo(corpo.para.primeiro_nome || "cliente");
const nome = esc(primeiro);
const site = String(corpo.site || "https://projetocasalorenzi.vercel.app").replace(/\/$/, "");
const LOGO = `${site}/img/logo-casa-lorenzi.png`;

// ------------------------------------------------------------------ peças de layout

const botao = (texto, link) => `<table role="presentation" cellpadding="0" cellspacing="0" style="margin:8px 0 4px"><tr>
<td style="background:${COR.marinho};border-radius:2px"><a href="${esc(link)}" style="display:inline-block;padding:14px 28px;font-family:${SANS};font-size:13px;letter-spacing:1.5px;text-transform:uppercase;color:#ffffff;text-decoration:none">${esc(texto)}</a></td>
</tr></table>`;

const rotulo = (texto) => `<p style="margin:0 0 6px;font-family:${SANS};font-size:11px;letter-spacing:2px;text-transform:uppercase;color:${COR.dourado}">${texto}</p>`;

const cartao = (conteudo, fundo = COR.douradoClaro) => `<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:20px 0;background:${fundo};border-radius:2px"><tr><td style="padding:20px 22px">${conteudo}</td></tr></table>`;

function barra(percentual) {
  const p = Math.max(4, Math.min(100, Math.round(percentual || 0)));
  return `<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:10px 0 6px;background:${COR.areia};border-radius:8px"><tr>
<td width="${p}%" style="background:${COR.dourado};height:8px;line-height:8px;font-size:0;border-radius:8px">&nbsp;</td>${p < 100 ? `<td style="height:8px;line-height:8px;font-size:0">&nbsp;</td>` : ""}
</tr></table>`;
}

function beneficios(lista) {
  return (lista || []).map((b) => `<tr>
<td valign="top" style="padding:6px 10px 6px 0;font-family:${SERIFA};font-size:16px;color:${COR.dourado}">&#10003;</td>
<td style="padding:6px 0;font-family:${SANS};font-size:14px;line-height:1.5;color:${COR.tinta}"><strong>${esc(b.titulo)}</strong><br><span style="color:${COR.suave}">${esc(b.descricao)}</span></td>
</tr>`).join("");
}

function blocoCategoria(categoria, chamada) {
  const prox = categoria && categoria.proxima;
  if (!prox) return "";
  const lista = beneficios(prox.beneficios);
  return cartao(`${rotulo("Lorenzi+")}
<p style="margin:0;font-family:${SERIFA};font-size:20px;line-height:1.3;color:${COR.tinta}">${chamada || `Faltam <strong>${pontosTxt(prox.faltam)}</strong> para o ${esc(prox.nome)}`}</p>
${barra(prox.progresso)}
<p style="margin:0 0 ${lista ? "12px" : "0"};font-family:${SANS};font-size:12px;color:${COR.suave}">${esc(categoria.atual.nome)} &rarr; ${esc(prox.nome)} · faltam ${pontosTxt(prox.faltam)}</p>
${lista ? `<p style="margin:0 0 4px;font-family:${SANS};font-size:13px;color:${COR.tinta}">No ${esc(prox.nome)} você passa a ter:</p><table role="presentation" cellpadding="0" cellspacing="0">${lista}</table>` : ""}`);
}

function moldura({ preheader, titulo: tituloHtml, conteudo, rodapeExtra }) {
  return `<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light"><title>Casa Lorenzi</title></head>
<body style="margin:0;padding:0;background:${COR.fundo}">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:${COR.fundo}">${esc(preheader)}&#847;&zwnj;&nbsp;&#847;&zwnj;&nbsp;&#847;&zwnj;&nbsp;</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:${COR.fundo}"><tr><td align="center" style="padding:28px 12px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px">
<tr><td align="center" style="padding:8px 0 22px"><a href="${esc(site)}" style="text-decoration:none"><img src="${esc(LOGO)}" width="112" height="112" alt="Casa Lorenzi" style="display:block;border:0;width:112px;height:112px"></a></td></tr>
<tr><td style="background:${COR.papel};border:1px solid ${COR.linha};border-top:3px solid ${COR.vinho}">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
<tr><td style="padding:36px 40px 4px;font-family:${SERIFA};font-size:28px;line-height:1.25;color:${COR.tinta}">${tituloHtml}</td></tr>
<tr><td style="padding:14px 40px 34px;font-family:${SANS};font-size:15px;line-height:1.65;color:${COR.tinta}">${conteudo}</td></tr>
</table></td></tr>
<tr><td style="padding:24px 20px 8px;text-align:center;font-family:${SANS};font-size:12px;line-height:1.6;color:${COR.suave}">
${rodapeExtra ? `${rodapeExtra}<br><br>` : ""}
<a href="${esc(site)}/loja" style="color:${COR.suave}">Loja</a> &nbsp;·&nbsp; <a href="${esc(site)}/casas" style="color:${COR.suave}">Nossas casas</a> &nbsp;·&nbsp; <a href="${esc(site)}/agendar" style="color:${COR.suave}">Agendar atendimento</a> &nbsp;·&nbsp; <a href="${esc(site)}/conta" style="color:${COR.suave}">Minha conta</a><br><br>
Você recebeu este e-mail porque é cliente da Casa Lorenzi.<br>Para deixar de receber avisos, altere suas preferências em <a href="${esc(site)}/conta" style="color:${COR.suave}">Minha conta</a>.
</td></tr>
</table></td></tr></table></body></html>`;
}

// ------------------------------------------------------------------ os três e-mails

let assunto, html, texto;

if (corpo.tipo === "pos_compra") {
  const p = corpo.pedido;
  const loja = titulo(p.loja);
  const itens = (p.itens || []).map((i) => `<tr>
<td width="76" valign="top" style="padding:14px 14px 14px 0;border-bottom:1px solid ${COR.linha}">${i.imagem ? `<img src="${esc(i.imagem)}" width="64" height="80" alt="" style="display:block;width:64px;height:80px;object-fit:cover;border:0;background:${COR.areia}">` : `<div style="width:64px;height:80px;background:${COR.areia}"></div>`}</td>
<td valign="top" style="padding:14px 0;border-bottom:1px solid ${COR.linha};font-family:${SANS};font-size:14px;line-height:1.5;color:${COR.tinta}"><strong style="font-family:${SERIFA};font-size:16px;font-weight:normal">${esc(titulo(i.nome || i.produto))}</strong><br><span style="color:${COR.suave};font-size:13px">${esc([i.cor && titulo(i.cor), i.tamanho && `Tam. ${i.tamanho}`].filter(Boolean).join(" · "))}${i.quantidade > 1 ? ` · ${inteiro(i.quantidade)} × ${moeda(i.preco_unitario)}` : ""}</span></td>
<td valign="top" align="right" style="padding:14px 0 14px 12px;border-bottom:1px solid ${COR.linha};font-family:${SANS};font-size:14px;white-space:nowrap;color:${COR.tinta}">${moeda(i.total)}</td>
</tr>`).join("");
  const linhaTotal = (rot, valor, forte) => `<tr><td style="padding:6px 0;font-family:${SANS};font-size:${forte ? 16 : 14}px;color:${forte ? COR.tinta : COR.suave}">${forte ? `<strong>${rot}</strong>` : rot}</td><td align="right" style="padding:6px 0;font-family:${SANS};font-size:${forte ? 16 : 14}px;color:${COR.tinta}">${forte ? `<strong>${valor}</strong>` : valor}</td></tr>`;
  const pontos = corpo.pontos && Number(corpo.pontos.ganhos) > 0
    ? cartao(`${rotulo("Lorenzi+")}<p style="margin:0;font-family:${SERIFA};font-size:20px;color:${COR.tinta}">Você ganhou <strong>${pontosTxt(corpo.pontos.ganhos)}</strong></p><p style="margin:6px 0 0;font-family:${SANS};font-size:13px;color:${COR.suave}">Seu saldo agora é de ${pontosTxt(corpo.pontos.saldo)}. Use como desconto na próxima compra.</p>`)
    : "";
  const ondeComprou = p.canal === "online" ? "no nosso site" : `na <strong>${esc(loja)}</strong>`;
  assunto = `${primeiro}, obrigado pela sua compra na Casa Lorenzi`;
  html = moldura({
    preheader: `Pedido ${p.numero} · ${moeda(p.total)} · ${dataLonga(p.data)}`,
    titulo: `Obrigado, ${nome}.`,
    conteudo: `<p style="margin:0 0 22px">Foi um prazer receber você ${ondeComprou}. Aqui está o resumo da sua compra de ${dataLonga(p.data)}.</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 8px"><tr>
<td style="font-family:${SANS};font-size:12px;letter-spacing:1.5px;text-transform:uppercase;color:${COR.suave}">Pedido ${esc(p.numero)}</td>
<td align="right" style="font-family:${SANS};font-size:12px;color:${COR.suave}">${p.pagamento ? esc(p.pagamento) : ""}</td>
</tr></table>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-top:1px solid ${COR.tinta}">${itens}</table>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:10px 0 0">
${Number(p.frete) > 0 ? linhaTotal("Frete", moeda(p.frete)) : ""}${linhaTotal("Total", moeda(p.total), true)}
</table>
${pontos}
<p style="margin:22px 0 18px">Precisa de um ajuste na barra ou na cintura? É só agendar um horário com a nossa alfaiataria.</p>
${botao("Ver minhas compras", `${site}/conta/pedidos`)}
<p style="margin:22px 0 0;font-family:${SANS};font-size:12px;color:${COR.suave}">Este e-mail é um resumo da compra e não substitui a nota fiscal.</p>`,
    rodapeExtra: p.loja_endereco ? `${esc(loja)} · ${esc(titulo(p.loja_endereco))}` : "",
  });
  texto = `Obrigado pela sua compra! Pedido ${p.numero}, total ${moeda(p.total)}.`;
} else if (corpo.tipo === "pontos") {
  const pt = corpo.pontos;
  const vencimentos = pt.vencimentos || [];
  const primeira = vencimentos[0];
  const lista = vencimentos.map((v) => `<tr>
<td style="padding:10px 0;border-bottom:1px solid ${COR.linha};font-family:${SANS};font-size:14px;color:${COR.tinta}">${dataLonga(v.data)}</td>
<td align="right" style="padding:10px 0;border-bottom:1px solid ${COR.linha};font-family:${SANS};font-size:14px;color:${COR.tinta}"><strong>${pontosTxt(v.pontos)}</strong></td>
</tr>`).join("");
  assunto = `${primeiro}, ${pontosTxt(pt.a_vencer)} vencem ${primeira ? `em ${dataCurta(primeira.data)}` : "em breve"}`;
  html = moldura({
    preheader: `Use seus pontos Lorenzi+ antes que eles vençam. Saldo: ${pontosTxt(pt.saldo)}.`,
    titulo: `${nome}, seus pontos estão perto de vencer.`,
    conteudo: `<p style="margin:0 0 4px">Você tem pontos Lorenzi+ que vencem nos próximos dias. Eles valem desconto em qualquer compra, no site ou nas nossas casas.</p>
${cartao(`<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
<td>${rotulo("Vencem em breve")}<p style="margin:0;font-family:${SERIFA};font-size:40px;line-height:1;color:${COR.vinho}">${inteiro(pt.a_vencer)}</p><p style="margin:6px 0 0;font-family:${SANS};font-size:13px;color:${COR.suave}">${Number(pt.a_vencer) === 1 ? "ponto" : "pontos"}</p></td>
<td align="right" valign="bottom">${rotulo("Saldo total")}<p style="margin:0;font-family:${SERIFA};font-size:22px;color:${COR.tinta}">${pontosTxt(pt.saldo)}</p></td>
</tr></table>`)}
${lista ? `<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 22px;border-top:1px solid ${COR.tinta}">${lista}</table>` : ""}
${botao("Usar meus pontos", `${site}/loja`)}
${blocoCategoria(corpo.categoria)}
<p style="margin:0;font-family:${SANS};font-size:13px;color:${COR.suave}">Veja seu extrato completo em <a href="${esc(site)}/conta/lorenzi-mais" style="color:${COR.marinho}">Minha conta &rarr; Lorenzi+</a>.</p>`,
  });
  texto = `Você tem ${pontosTxt(pt.a_vencer)} Lorenzi+ vencendo. Saldo: ${pontosTxt(pt.saldo)}.`;
} else if (corpo.tipo === "categoria") {
  const cat = corpo.categoria;
  const prox = cat && cat.proxima;
  if (!prox) throw new Error("Aviso de categoria sem próxima categoria");
  assunto = `${primeiro}, você está a ${pontosTxt(prox.faltam)} do ${prox.nome}`;
  html = moldura({
    preheader: `Veja o que muda quando você chegar ao ${prox.nome} do Lorenzi+.`,
    titulo: `${nome}, o ${esc(prox.nome)} está logo ali.`,
    conteudo: `<p style="margin:0 0 4px">Hoje você é cliente <strong>${esc(cat.atual.nome)}</strong> do Lorenzi+ e já percorreu ${Math.round(prox.progresso || 0)}% do caminho até a próxima categoria.</p>
${blocoCategoria(cat, `Faltam <strong>${pontosTxt(prox.faltam)}</strong> para você chegar ao ${esc(prox.nome)}`)}
<p style="margin:0 0 18px">Cada compra soma pontos, e você tem <strong>${pontosTxt(corpo.pontos.saldo)}</strong> hoje para usar como desconto.</p>
${botao("Ver a loja", `${site}/loja`)}`,
  });
  texto = `Faltam ${pontosTxt(prox.faltam)} para a categoria ${prox.nome} do Lorenzi+.`;
} else {
  throw new Error(`Tipo de e-mail desconhecido: ${corpo.tipo}`);
}

return { json: { para: corpo.para.email, assunto, html, texto, tipo: corpo.tipo } };
