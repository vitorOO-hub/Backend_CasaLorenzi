"""Confere se a resposta do modelo manteve as listas ordenadas exatamente como o backend mandou.

Ranking, ordem e totais sao calculados no SQL. O modelo so apresenta: se ele reordenou, omitiu um
item ou trocou um valor, a resposta e trocada por um texto montado aqui, a partir do resultado da
ferramenta. Assim o vendedor nunca ve uma ordem ou um numero que o banco nao deu.
"""

import re
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.assistente.vendedor.provedores import ChamadaFeita


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", str(texto).casefold())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    # "14 507,80", "14.507,80" e "14507,80" viram o mesmo numero.
    return re.sub(r"(?<=\d)[\s.  ](?=\d{3}\b)", "", texto)


def moeda(valor: float) -> str:
    inteiro, centavos = f"{valor:,.2f}".split(".")
    return f"R$ {inteiro.replace(',', '.')},{centavos}"


def _so_numero(valor: float) -> str:
    return _normalizar(moeda(valor).removeprefix("R$ "))


def _dia(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%d/%m/%Y")


_MINUSCULAS = {"de", "da", "do", "das", "dos", "e"}


def _nome(texto: str) -> str:
    return " ".join(p if p in _MINUSCULAS else p[:1].upper() + p[1:] for p in str(texto).split())


@dataclass(frozen=True)
class Lista:
    chave: str  # campo da lista no resultado da ferramenta
    rotulo: str  # campo que identifica o item na resposta
    valor: str  # campo em dinheiro que tem de aparecer igual
    texto: Callable[[dict[str, Any]], str]  # resposta montada pelo backend
    # Obrigatoria: a lista e a resposta (ranking). Senao, so confere se o modelo a mostrou.
    obrigatoria: bool = True


def _criterio(r: dict[str, Any]) -> str:
    return f"Critério: {r['criterio'][:1].lower()}{r['criterio'][1:]}"


def _texto_clientes(r: dict[str, Any]) -> str:
    linhas = [f"Clientes que mais compraram na sua loja de {_dia(r['inicio'])} a {_dia(r['fim'])}:"]
    for c in r["clientes"]:
        linhas.append(
            f"{c['posicao']}. {_nome(c['nome'])}: {moeda(c['total'])} em {c['pedidos']} "
            f"{'pedido' if c['pedidos'] == 1 else 'pedidos'}, última compra em "
            f"{_dia(c['ultima_compra'])}"
        )
    linhas.append(_criterio(r))
    if r.get("padroes_usados"):
        linhas.append(f"Padrão usado: {' e '.join(r['padroes_usados'])}.")
    return "\n".join(linhas)


def _diz_o_periodo(resposta: str, resultado: dict[str, Any]) -> bool:
    """Com periodo padrao, a resposta tem de dizer qual foi (as datas ou "ultimos N dias")."""
    if not any("periodo" in _normalizar(p) for p in resultado.get("padroes_usados", [])):
        return True
    texto = _normalizar(resposta)
    return _dia(resultado["inicio"]) in texto or bool(re.search(r"\b\d+ dias\b", texto))


def _texto_vendas(r: dict[str, Any]) -> str:
    periodo = (
        f"em {_dia(r['inicio'])}"
        if r["inicio"] == r["fim"]
        else f"de {_dia(r['inicio'])} a {_dia(r['fim'])}"
    )
    linhas = [
        f"Vendas da loja {periodo}: {moeda(r['faturamento'])} em {r['pedidos']} pedidos, "
        f"{r['pecas']} peças, ticket médio de {moeda(r['ticket_medio'])}."
    ]
    if r["mais_vendidas"]:
        linhas.append("Peças mais vendidas:")
        linhas += [
            f"{p['posicao']}. {p['produto']}: {p['unidades']} unidades, {moeda(p['faturamento'])}"
            for p in r["mais_vendidas"]
        ]
    linhas.append(_criterio(r))
    return "\n".join(linhas)


LISTAS = {
    "clientes_que_mais_compram": Lista("clientes", "nome", "total", _texto_clientes),
    "vendas_do_periodo": Lista(
        "mais_vendidas", "produto", "faturamento", _texto_vendas, obrigatoria=False
    ),
}


def _lista_confere(resposta: str, itens: list[dict[str, Any]], lista: Lista) -> bool:
    texto = _normalizar(resposta)
    rotulos = [_normalizar(item[lista.rotulo]) for item in itens]
    if not lista.obrigatoria and not any(r in texto for r in rotulos):
        return True  # o modelo nao apresentou a lista (ex.: so o total do dia)
    posicao = 0
    for i, item in enumerate(itens):
        achado = texto.find(rotulos[i], posicao)
        if achado < 0:
            return False
        posicao = achado + len(rotulos[i])
        # O valor do item tem de estar entre o rotulo dele e o rotulo do proximo.
        fim = texto.find(rotulos[i + 1], posicao) if i + 1 < len(itens) else -1
        trecho = texto[posicao:] if fim < 0 else texto[posicao:fim]
        if _so_numero(item[lista.valor]) not in trecho:
            return False
    return True


# ------------------------------------------------------------------ contagem de estoque

_DIZ_QUE_NAO_HA = re.compile(
    r"\b(nao ha|nao temos|nao tem|nenhum|nenhuma|zero|sem estoque|esgotad\w*|nao encontrei)\b"
)


def diz_que_nao_ha(resposta: str) -> bool:
    return bool(_DIZ_QUE_NAO_HA.search(_normalizar(resposta)))


FALHA_NO_ESTOQUE = "Não consegui consultar o estoque agora. Tente de novo em instantes."


def _tem_numero(texto: str, numero: int) -> bool:
    return bool(re.search(rf"(?<![\d,]){numero}(?![\d,])", texto))


def _unidades(n: int) -> str:
    return f"{n:,}".replace(",", ".") + (" unidade" if n == 1 else " unidades")


def _texto_estoque(r: dict[str, Any]) -> str:
    filtros = r["filtros_aplicados"]
    if r["total_unidades"] == 0:
        return f"Não encontrei peças disponíveis com {filtros} na loja {_nome(r['loja'])}."
    modelos = r["total_modelos"]
    linhas = [
        f"Na loja {_nome(r['loja'])}, com {filtros}: **{_unidades(r['total_unidades'])}** em "
        f"**{modelos} {'modelo' if modelos == 1 else 'modelos'}**."
    ]
    if r["detalhamento"]:
        chave = next(k for k in r["detalhamento"][0] if k not in ("unidades", "modelos"))
        partes = [f"{d[chave]} {d['unidades']}" for d in r["detalhamento"][:6]]
        linhas.append(f"Por {chave}: {', '.join(partes)}.")
    return "\n".join(linhas)


def _texto_filtro_invalido(r: dict[str, Any]) -> str:
    partes = []
    for campo, valor in r["filtro_invalido"].items():
        validos = r["valores_validos"]["tamanhos" if campo == "tamanho" else "categorias"]
        partes.append(
            f"Não existe {campo} '{valor}' no catálogo. Os que existem: {', '.join(validos)}."
        )
    return " ".join(partes)


def conferir_estoque(resposta: str, chamadas: Sequence[ChamadaFeita]) -> str | None:
    """A ultima contagem de estoque manda: numero igual ao da ferramenta, zero so quando ela
    confirmou zero, e erro ou filtro inexistente nunca viram "nao ha"."""
    chamada = next((c for c in reversed(chamadas) if c.nome == "consultar_estoque"), None)
    if chamada is None:
        return None
    r, texto = chamada.resultado, _normalizar(resposta)
    if "erro" in r:
        return FALHA_NO_ESTOQUE if _DIZ_QUE_NAO_HA.search(texto) or _tem_numero(texto, 0) else None
    if "filtro_invalido" in r:
        diz_zero = _DIZ_QUE_NAO_HA.search(texto) and "existe" not in texto
        return _texto_filtro_invalido(r) if diz_zero or _tem_numero(texto, 0) else None
    total = r["total_unidades"]
    if total == 0:
        return None if _DIZ_QUE_NAO_HA.search(texto) or _tem_numero(texto, 0) else _texto_estoque(r)
    return None if _tem_numero(texto, total) else _texto_estoque(r)


def conferir(resposta: str, chamadas: Sequence[ChamadaFeita]) -> str | None:
    """Texto do backend para trocar a resposta, ou None se ela respeitou as listas."""
    do_estoque = conferir_estoque(resposta, chamadas)
    if do_estoque is not None:
        return do_estoque
    for chamada in reversed(chamadas):
        lista = LISTAS.get(chamada.nome)
        if lista is None or "erro" in chamada.resultado:
            continue
        itens = chamada.resultado.get(lista.chave) or []
        if itens and not (
            _lista_confere(resposta, itens, lista) and _diz_o_periodo(resposta, chamada.resultado)
        ):
            return lista.texto(chamada.resultado)
    return None
