"""Retoma uma consulta quando a resposta seguinte informa apenas o período."""

import re
import unicodedata
from collections.abc import Callable
from typing import Any

PEDIDO_PERIODO = "Qual período você quer consultar? Informe as datas inicial e final."
RESPOSTA_PERIODO = re.compile(
    r"(?:(?:d[oa]s?|n[oa]s?|em|durante|entre|nesses|nessas|esses|essas)\s+)?(?:"
    r"(?:ultim[oa]s?|passad[oa]s?)\s+\d+\s+(?:dias?|semanas?|mes(?:es)?|anos?)|"
    r"\d+\s+(?:dias?|semanas?|mes(?:es)?|anos?)(?:\s+(?:anteriores|passad[oa]s?))?|"
    r"(?:est[ea]|ess[ea]|dest[ea]|dess[ea]|nest[ea]|ness[ea]|"
    r"ultim[oa]|passad[oa])\s+(?:semana|mes|ano)|"
    r"(?:semana|mes|ano)\s+(?:passad[oa]|atual|corrente)|"
    r"ano\s+de\s+\d{4}|"
    r"(?:mes\s+de\s+)?(?:janeiro|fevereiro|marco|abril|maio|junho|julho|"
    r"agosto|setembro|outubro|novembro|dezembro)(?:\s+de\s+\d{4})?|"
    r"hoje|ontem|anteontem|\d{4}|"
    r"\d{1,2}/\d{1,2}(?:/\d{2,4})?(?:\s+(?:a|ate)\s+"
    r"\d{1,2}/\d{1,2}(?:/\d{2,4})?)?"
    r")[.!?]?"
)


def normalizar(texto: str) -> str:
    decomposed = unicodedata.normalize("NFKD", texto.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def contextualizar(
    pergunta: str, historico: list[dict[str, Any]], *, aceitar_assunto: Callable[[str], bool]
) -> str:
    if len(historico) < 3 or not RESPOSTA_PERIODO.fullmatch(normalizar(pergunta.strip())):
        return pergunta
    if historico[-1].get("role") != "user" or historico[-1].get("content") != pergunta:
        return pergunta
    anteriores = historico[:-1]
    recusa = "Este assistente responde somente sobre vendas e indicadores da sua unidade, "
    while len(anteriores) >= 2:
        resposta, anterior = anteriores[-1], anteriores[-2]
        if resposta.get("role") != "assistant" or anterior.get("role") != "user":
            return pergunta
        if resposta.get("content") == PEDIDO_PERIODO:
            break
        texto = anterior.get("content", "")
        if (
            not isinstance(resposta.get("content"), str)
            or not resposta["content"].startswith(recusa)
            or not isinstance(texto, str)
            or not RESPOSTA_PERIODO.fullmatch(normalizar(texto.strip()))
        ):
            return pergunta
        anteriores = anteriores[:-2]
    else:
        return pergunta
    texto_anterior = anterior.get("content", "")
    if not isinstance(texto_anterior, str) or not aceitar_assunto(texto_anterior):
        return pergunta
    return f"{texto_anterior} {pergunta}"
