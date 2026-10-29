"""E-mails do operador de estoque (diario e semanal), prontos para o n8n so enviar.

HTML simples com estilo inline (e o que os clientes de e-mail respeitam), nas cores da Casa Lorenzi.
Todo texto que vem do banco passa por `escape`.
"""

from datetime import date, datetime
from html import escape
from typing import Any

from app.cliente.vencimento_pontos import SP

TD = 'style="padding:6px 8px;border-bottom:1px solid #dfd9cf;vertical-align:top"'
TH = (
    'style="padding:6px 8px;text-align:left;border-bottom:2px solid #1f2a48;font-size:12px;'
    'color:#5e6b89"'
)
TITULO = 'style="font-family:Georgia,serif;font-weight:normal;color:#1f2a48;margin:24px 0 8px"'
NOTA = 'style="font-size:12px;color:#5e6b89"'


def _data(valor: datetime | None, sem: str = "-") -> str:
    return valor.astimezone(SP).strftime("%d/%m/%Y") if valor else sem


def _reais(valor: float) -> str:
    inteiro, centavos = f"{valor:,.2f}".split(".")
    return f"R$ {inteiro.replace(',', '.')},{centavos}"


def _peca(p: dict[str, Any]) -> str:
    return (
        f"{escape(p['produto'])} · {escape(p['cor'])}, {escape(p['tamanho'])} "
        f'<span style="color:#5e6b89">({escape(p["sku"])})</span>'
    )


def _tabela(titulo: str, colunas: list[str], linhas: list[list[Any]], total: int) -> str:
    if not linhas:
        return ""
    cabeca = "".join(f"<th {TH}>{c}</th>" for c in colunas)
    corpo = "\n".join(
        "<tr>" + "".join(f"<td {TD}>{c}</td>" for c in linha) + "</tr>" for linha in linhas
    )
    resto = total - len(linhas)
    mais = f"<p {NOTA}>E mais {resto} no painel de estoque.</p>" if resto > 0 else ""
    return (
        f"<h3 {TITULO}>{titulo} ({total})</h3>"
        f'<table style="border-collapse:collapse;width:100%;font-size:14px"><tr>{cabeca}</tr>'
        f"\n{corpo}</table>{mais}"
    )


def _moldura(sobretitulo: str, loja: str, corpo: str, painel_url: str, rodape: str) -> str:
    return (
        '<div style="font-family:Arial,sans-serif;color:#16203a;max-width:720px">'
        '<p style="font-size:12px;letter-spacing:.16em;text-transform:uppercase;color:#b46746;'
        f'margin:0">{sobretitulo}</p>'
        '<h2 style="font-family:Georgia,serif;font-weight:normal;color:#1f2a48;margin:4px 0 0">'
        f"{escape(loja)}</h2>\n{corpo}\n"
        f'<p style="margin-top:24px"><a href="{escape(painel_url)}" style="color:#1f2a48">'
        "Abrir o painel de estoque</a></p>"
        f"<div {NOTA}>{rodape}</div></div>"
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
    loja: dict[str, Any], criterios: dict[str, str], hoje: date, painel_url: str, limite: int
) -> dict[str, str]:
    """Reposicao e pendencias da loja. A lista de pecas abaixo do minimo mostra ate `limite`
    (as de menor saldo primeiro, como vem da consulta); o resto fica no painel."""

    def sobra(p: dict[str, Any]) -> str:
        lojas = p["lojas_com_sobra"]
        if not lojas:
            return "nenhuma loja"
        return "<br>".join(f"{escape(s['loja'])} (+{s['sobra']})" for s in lojas)

    def transferencias(chave: str, titulo: str, rotulo: str, quem, quando: str) -> str:
        itens = loja[chave]
        linhas = [[_peca(t), t["quantidade"], escape(quem(t)), _data(t[quando])] for t in itens]
        return _tabela(titulo, ["Peça", "Qtd.", rotulo, "Data"], linhas, len(itens))

    abaixo = loja["abaixo_do_minimo"]
    ajustes = loja["ajustes_pendentes"]
    corpo = "\n".join(
        [
            _tabela(
                "Abaixo do mínimo",
                ["Peça", "Saldo", "Mínimo", "Pedir para"],
                [[_peca(p), p["saldo"], p["minimo"], sobra(p)] for p in abaixo[:limite]],
                len(abaixo),
            ),
            transferencias(
                "para_responder",
                "Pedidos de outras lojas para responder",
                "Quem pediu",
                lambda t: t["destino"],
                "solicitada_em",
            ),
            transferencias(
                "pedidos_sem_resposta",
                "Seus pedidos ainda sem resposta",
                "Pedido a",
                lambda t: t["origem"] or "rede (qualquer loja)",
                "solicitada_em",
            ),
            transferencias(
                "a_receber",
                "Em trânsito: confirme o recebimento",
                "Vem de",
                lambda t: t["origem"] or "rede",
                "aceita_em",
            ),
            _tabela(
                "Ajustes de inventário aguardando aprovação",
                ["Peça", "Qtd.", "Motivo", "Pedido por"],
                [
                    [
                        _peca(a),
                        f"+{a['quantidade']}" if a["quantidade"] > 0 else a["quantidade"],
                        escape(a["motivo"]),
                        f"{escape(a['solicitante'])}, {_data(a['solicitado_em'])}",
                    ]
                    for a in ajustes
                ],
                len(ajustes),
            ),
        ]
    )
    rodape = (
        '<ul style="padding-left:16px">'
        + "".join(f"<li>{escape(c)}</li>" for c in criterios.values())
        + "</ul>"
    )
    total = _total_do_dia(loja)
    return {
        "assunto": (
            f"Estoque do dia · {loja['loja']}: {total} "
            f"{'item' if total == 1 else 'itens'} para resolver"
        ),
        "html": _moldura(
            f"Casa Lorenzi · Estoque do dia · {hoje:%d/%m/%Y}",
            loja["loja"],
            corpo,
            painel_url,
            rodape,
        ),
    }


def semanal(
    loja: dict[str, Any], dias: int, criterio: str, hoje: date, painel_url: str
) -> dict[str, str]:
    total = loja["total_itens"]
    pecas = "peça" if total == 1 else "peças"
    resumo = (
        f"<p>{total} {pecas} ({loja['total_unidades']} unidades, {_reais(loja['total_valor'])}) "
        f"sem venda há mais de {dias} dias. Avalie transferir para outra loja ou sugerir uma "
        "ação de venda.</p>"
    )
    tabela = _tabela(
        "Peças de maior valor parado",
        ["Peça", "Saldo", "Valor parado", "Última venda"],
        [
            [_peca(p), p["saldo"], _reais(p["valor_parado"]), _data(p["ultima_venda"], "nunca")]
            for p in loja["itens"]
        ],
        total,
    )
    return {
        "assunto": f"Estoque parado · {loja['loja']}: {total} {pecas} sem venda há {dias}+ dias",
        "html": _moldura(
            f"Casa Lorenzi · Estoque parado · semana de {hoje:%d/%m/%Y}",
            loja["loja"],
            resumo + tabela,
            painel_url,
            escape(criterio),
        ),
    }
