"""E-mails do operador de estoque (diario e semanal), prontos para o n8n so enviar.

Mesmo desenho dos e-mails ao cliente (n8n/montar_email.js): logo, cartao branco com filete vinho,
titulos em serifa, rotulos em caixa alta e botao marinho. HTML de e-mail: so tabelas e estilo
inline (Gmail, Outlook e celular). Todo texto que vem do banco passa por `escape`.
"""

from datetime import date, datetime
from html import escape
from typing import Any

from app.cliente.vencimento_pontos import SP

FUNDO, PAPEL, TINTA, SUAVE, LINHA = "#f6f3ee", "#ffffff", "#16203a", "#5e6b89", "#e7e1d7"
MARINHO, DOURADO, DOURADO_CLARO, VINHO = "#1f2a48", "#b46746", "#f8ece4", "#7a1020"
SERIFA = "Georgia,'Times New Roman',serif"
SANS = "'Helvetica Neue',Helvetica,Arial,sans-serif"
MINUSCULAS = {"de", "da", "do", "das", "dos", "e", "em", "com"}


def _titulo(texto: str | None) -> str:
    """O banco guarda nomes em minusculas: no e-mail, cada palavra com maiuscula (como no e-mail
    ao cliente). Tamanhos e siglas curtas em maiusculas ficam como estao."""
    palavras = []
    for i, palavra in enumerate(str(texto or "").split()):
        if i > 0 and palavra.lower() in MINUSCULAS:
            palavras.append(palavra.lower())
        elif len(palavra) <= 3 and palavra.isupper():
            palavras.append(palavra)
        else:
            palavras.append(palavra[:1].upper() + palavra[1:].lower())
    return " ".join(palavras)


def _data(valor: datetime | None, sem: str = "-") -> str:
    return valor.astimezone(SP).strftime("%d/%m/%Y") if valor else sem


def _reais(valor: float) -> str:
    inteiro, centavos = f"{valor:,.2f}".split(".")
    return f"R$ {inteiro.replace(',', '.')},{centavos}"


def _inteiro(valor: int) -> str:
    return f"{valor:,}".replace(",", ".")


def _rotulo(texto: str) -> str:
    return (
        f'<p style="margin:0 0 6px;font-family:{SANS};font-size:11px;letter-spacing:2px;'
        f'text-transform:uppercase;color:{DOURADO}">{texto}</p>'
    )


def _botao(texto: str, link: str) -> str:
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" style="margin:8px 0 4px"><tr>'
        f'<td style="background:{MARINHO};border-radius:2px"><a href="{escape(link)}" '
        f'style="display:inline-block;padding:14px 28px;font-family:{SANS};font-size:13px;'
        f'letter-spacing:1.5px;text-transform:uppercase;color:#ffffff;text-decoration:none">'
        f"{escape(texto)}</a></td></tr></table>"
    )


def _destaques(numeros: list[tuple[str, str, str]]) -> str:
    """Quadro claro com os numeros grandes do e-mail: (rotulo, numero, legenda)."""
    colunas = "".join(
        f'<td valign="top" style="padding-right:16px">{_rotulo(rotulo)}'
        f'<p style="margin:0;font-family:{SERIFA};font-size:36px;line-height:1;color:{VINHO}">'
        f"{numero}</p>"
        f'<p style="margin:6px 0 0;font-family:{SANS};font-size:13px;color:{SUAVE}">{legenda}</p>'
        "</td>"
        for rotulo, numero, legenda in numeros
    )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="margin:20px 0;background:{DOURADO_CLARO};border-radius:2px"><tr>'
        f'<td style="padding:20px 22px"><table role="presentation" width="100%" cellpadding="0" '
        f'cellspacing="0"><tr>{colunas}</tr></table></td></tr></table>'
    )


def _peca(p: dict[str, Any], detalhe: str = "") -> str:
    nome = (
        f'<strong style="font-family:{SERIFA};font-size:16px;font-weight:normal">'
        f"{escape(_titulo(p['produto']))}</strong>"
    )
    linha = f"{escape(_titulo(p['cor']))} · Tam. {escape(p['tamanho'])} · {escape(p['sku'])}"
    extra = f"<br>{detalhe}" if detalhe else ""
    return f'{nome}<br><span style="color:{SUAVE};font-size:13px">{linha}{extra}</span>'


def _secao(titulo: str, linhas: list[tuple[str, str]], total: int, painel_url: str) -> str:
    """Rotulo, tabela com filete escuro no topo e uma linha por item (descricao, valor a direita).
    Se a lista foi cortada, avisa quantos ficaram no painel."""
    if not linhas:
        return ""
    celula = (
        f"padding:14px 0;border-bottom:1px solid {LINHA};font-family:{SANS};font-size:14px;"
        f"line-height:1.5;color:{TINTA}"
    )
    corpo = "".join(
        f'<tr><td valign="top" style="{celula}">{descricao}</td>'
        f'<td valign="top" align="right" style="{celula};padding-left:12px;white-space:nowrap">'
        f"{valor}</td></tr>"
        for descricao, valor in linhas
    )
    resto = total - len(linhas)
    mais = (
        f'<p style="margin:10px 0 0;font-family:{SANS};font-size:13px;color:{SUAVE}">E mais '
        f'{_inteiro(resto)} no <a href="{escape(painel_url)}" style="color:{MARINHO}">painel de '
        "estoque</a>.</p>"
        if resto > 0
        else ""
    )
    return (
        f'<div style="margin:28px 0 0">{_rotulo(f"{titulo} · {_inteiro(total)}")}'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="border-top:1px solid {TINTA}">{corpo}</table>{mais}</div>'
    )


def _moldura(
    *, site: str, preheader: str, titulo: str, conteudo: str, rodape: str, observacao: str = ""
) -> str:
    logo = f"{site}/img/logo-casa-lorenzi.png"
    nota = f"{observacao}<br><br>" if observacao else ""
    return (
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light"><title>Casa Lorenzi</title></head>'
        f'<body style="margin:0;padding:0;background:{FUNDO}">'
        f'<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:{FUNDO}">'
        f"{escape(preheader)}</div>"
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="background:{FUNDO}"><tr><td align="center" style="padding:28px 12px">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="max-width:600px">'
        f'<tr><td align="center" style="padding:8px 0 22px"><a href="{escape(site)}" '
        f'style="text-decoration:none"><img src="{escape(logo)}" width="112" height="112" '
        'alt="Casa Lorenzi" style="display:block;border:0;width:112px;height:112px"></a></td></tr>'
        f'<tr><td style="background:{PAPEL};border:1px solid {LINHA};border-top:3px solid {VINHO}">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0">'
        f'<tr><td style="padding:36px 40px 4px;font-family:{SERIFA};font-size:28px;'
        f'line-height:1.25;color:{TINTA}">{titulo}</td></tr>'
        f'<tr><td style="padding:14px 40px 34px;font-family:{SANS};font-size:15px;'
        f'line-height:1.65;color:{TINTA}">{conteudo}</td></tr>'
        "</table></td></tr>"
        f'<tr><td style="padding:24px 20px 8px;text-align:center;font-family:{SANS};'
        f'font-size:12px;line-height:1.6;color:{SUAVE}">{nota}{rodape}</td></tr>'
        "</table></td></tr></table></body></html>"
    )


def _rodape(loja: str) -> str:
    return (
        "Você recebeu este e-mail porque é operador de estoque da "
        f"{escape(loja)}.<br>Relatório automático da Casa Lorenzi."
    )


def _total_do_dia(loja: dict[str, Any]) -> int:
    return sum(
        len(loja[nome])
        for nome in (
            "abaixo_do_minimo",
            "para_responder",
            "pedidos_sem_resposta",
            "a_receber",
            "ajustes_pendentes",
        )
    )


def diario(
    loja: dict[str, Any], hoje: date, site: str, limite: int, *, horas: int, dias: int
) -> dict[str, str]:
    """Reposicao e pendencias da loja. A lista de pecas abaixo do minimo mostra ate `limite`
    (as de menor saldo primeiro, como vem da consulta); o resto fica no painel."""
    painel_url = f"{site}/painel/estoque"
    nome = _titulo(loja["loja"])
    abaixo = loja["abaixo_do_minimo"]
    pendencias = _total_do_dia(loja) - len(abaixo)

    def sobra(p: dict[str, Any]) -> str:
        if not p["lojas_com_sobra"]:
            return "Nenhuma outra loja tem sobra"
        lojas = ", ".join(
            f"{escape(_titulo(s['loja']))} (+{s['sobra']})" for s in p["lojas_com_sobra"]
        )
        return f"Pedir a: {lojas}"

    def saldo(p: dict[str, Any]) -> str:
        cor = VINHO if p["saldo"] == 0 else TINTA
        return (
            f'<strong style="color:{cor}">{p["saldo"]}</strong>'
            f'<br><span style="color:{SUAVE};font-size:13px">mín. {p["minimo"]}</span>'
        )

    def transferencias(chave: str, titulo: str, quem, rotulo: str, quando: str) -> str:
        itens = loja[chave]
        linhas = [
            (
                _peca(t, f"{rotulo} {escape(quem(t))} em {_data(t[quando])}"),
                f"{t['quantidade']} un.",
            )
            for t in itens
        ]
        return _secao(titulo, linhas, len(itens), painel_url)

    ajustes = loja["ajustes_pendentes"]
    conteudo = "".join(
        [
            '<p style="margin:0 0 4px">Este é o resumo do que pede atenção hoje no estoque da '
            f"<strong>{escape(nome)}</strong>: peças que chegaram ao mínimo e pendências paradas "
            "com outras lojas.</p>",
            _destaques(
                [
                    ("Abaixo do mínimo", _inteiro(len(abaixo)), "peças para repor"),
                    ("Pendências", _inteiro(pendencias), "transferências e ajustes"),
                ]
            ),
            _secao(
                "Abaixo do mínimo",
                [(_peca(p, sobra(p)), saldo(p)) for p in abaixo[:limite]],
                len(abaixo),
                painel_url,
            ),
            transferencias(
                "para_responder",
                "Pedidos de outras lojas para responder",
                lambda t: _titulo(t["destino"]),
                "Pedido pela",
                "solicitada_em",
            ),
            transferencias(
                "pedidos_sem_resposta",
                "Seus pedidos ainda sem resposta",
                lambda t: _titulo(t["origem"]) if t["origem"] else "rede (qualquer loja)",
                "Pedido à",
                "solicitada_em",
            ),
            transferencias(
                "a_receber",
                "Em trânsito: confirme o recebimento",
                lambda t: _titulo(t["origem"]) if t["origem"] else "rede",
                "Enviado pela",
                "aceita_em",
            ),
            _secao(
                "Ajustes de inventário aguardando aprovação",
                [
                    (
                        _peca(
                            a,
                            f"{escape(a['motivo'])} · {escape(_titulo(a['solicitante']))}, "
                            f"{_data(a['solicitado_em'])}",
                        ),
                        f"+{a['quantidade']}" if a["quantidade"] > 0 else str(a["quantidade"]),
                    )
                    for a in ajustes
                ],
                len(ajustes),
                painel_url,
            ),
            '<div style="margin:28px 0 0">',
            _botao("Abrir o painel de estoque", painel_url),
            "</div>",
        ]
    )
    total = _total_do_dia(loja)
    criterios = (
        "Abaixo do mínimo: peças ativas com saldo igual ou abaixo do mínimo definido pela loja; "
        "a sugestão de pedido mostra até 3 lojas com saldo acima do mínimo delas. Pendências: "
        f"transferências sem resposta há mais de {horas} horas, em trânsito há mais de {dias} "
        "dias e ajustes de inventário aguardando aprovação."
    )
    return {
        "assunto": (
            f"Estoque do dia · {nome}: {total} {'item' if total == 1 else 'itens'} para resolver"
        ),
        "html": _moldura(
            site=site,
            preheader=(
                f"{len(abaixo)} peças abaixo do mínimo e {pendencias} pendências · {hoje:%d/%m/%Y}"
            ),
            titulo=f"O estoque de hoje na {escape(nome)}.",
            conteudo=conteudo,
            rodape=_rodape(nome),
            observacao=criterios,
        ),
    }


def semanal(loja: dict[str, Any], dias: int, hoje: date, site: str) -> dict[str, str]:
    painel_url = f"{site}/painel/estoque"
    nome = _titulo(loja["loja"])
    total = loja["total_itens"]
    pecas = "peça" if total == 1 else "peças"
    conteudo = "".join(
        [
            f'<p style="margin:0 0 4px">Estas são as peças da <strong>{escape(nome)}</strong> '
            f"que não vendem há mais de {dias} dias. Avalie transferir para uma loja onde elas "
            "giram melhor ou sugerir uma ação de venda.</p>",
            _destaques(
                [
                    (
                        "Peças paradas",
                        _inteiro(total),
                        f"{_inteiro(loja['total_unidades'])} unidades",
                    ),
                    ("Valor parado", _reais(loja["total_valor"]), "saldo × preço de venda"),
                ]
            ),
            _secao(
                "Maior valor parado",
                [
                    (
                        _peca(
                            p,
                            f"{p['saldo']} un. · última venda: "
                            f"{_data(p['ultima_venda'], 'nunca vendeu nesta loja')}",
                        ),
                        _reais(p["valor_parado"]),
                    )
                    for p in loja["itens"]
                ],
                total,
                painel_url,
            ),
            '<div style="margin:28px 0 0">',
            _botao("Abrir o painel de estoque", painel_url),
            "</div>",
        ]
    )
    return {
        "assunto": f"Estoque parado · {nome}: {total} {pecas} sem venda há {dias}+ dias",
        "html": _moldura(
            site=site,
            preheader=f"{total} {pecas} sem venda há {dias}+ dias · semana de {hoje:%d/%m/%Y}",
            titulo=f"Peças paradas na {escape(nome)}.",
            conteudo=conteudo,
            rodape=_rodape(nome),
            observacao=(
                "Peças com saldo na loja e nenhuma venda (paga, separada ou entregue) da mesma "
                f"cor e tamanho nesta loja nos últimos {dias} dias. Valor parado = saldo × preço "
                "de venda. Só lojas físicas."
            ),
        ),
    }
