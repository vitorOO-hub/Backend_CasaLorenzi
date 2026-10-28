"""Frases montadas pelo backend para as consultas de cliente (sem modelo).

Usadas no template deterministico (CPF, e-mail, telefone), nas respostas fixas (nao encontrei,
homonimos, muitos resultados) e quando a resposta do modelo sobre compras nao bate com os totais
da ferramenta. Os numeros vem do resultado, identicos.
"""

import re
import unicodedata
from collections.abc import Sequence
from typing import Any

from app.assistente.vendedor.clientes import CHAVE_CURTA, ROTULO
from app.assistente.vendedor.conferencia import moeda
from app.assistente.vendedor.provedores import ChamadaFeita

FALHA = "Não consegui consultar os dados do cliente agora. Tente de novo em instantes."
AVISO_CPF = "No painel do vendedor, o CPF aparece só com os dois últimos dígitos."


def _itens(n: int) -> str:
    return f"{n} {'item' if n == 1 else 'itens'}"


def texto_da_busca(r: dict[str, Any], campos: Sequence[str] = ()) -> str:
    """Resposta para o resultado de `buscar_cliente`: um cliente, varios, muitos ou nenhum."""
    if "erro" in r:
        return FALHA
    for chave in ("nao_encontrado", "muitos"):
        if chave in r:
            return r[chave]
    if "opcoes" in r:
        linhas = [f"Encontrei {len(r['opcoes'])} clientes com esse nome na sua loja:"]
        linhas += [
            f"{o['n']}. {o['nome']}, CPF {o['cpf']}, última compra: {o['ultima_compra']}"
            for o in r["opcoes"]
        ]
        linhas.append(r["pergunta"])
        return "\n".join(linhas)
    partes = [f"{ROTULO[c]} {r[CHAVE_CURTA[c]]}" for c in campos if CHAVE_CURTA[c] in r]
    linhas = [f"**{r['nome']}**" + (f": {', '.join(partes)}." if partes else ".")]
    if r.get("sem_cadastro"):
        linhas.append(f"Sem {' e '.join(r['sem_cadastro'])} no cadastro.")
    if "cpf" in campos and "cpf" in r:
        linhas.append(AVISO_CPF)
    return "\n".join(linhas)


def texto_das_compras(r: dict[str, Any]) -> str:
    if "erro" in r:
        return r["erro"] if r["erro"].startswith(("A data", "Não entendi")) else FALHA
    if "nao_encontrado" in r:
        return r["nao_encontrado"]
    linhas = [r["aviso"]] if r.get("aviso") else []
    em = f"em {r['periodo']}" if " a " not in r["periodo"] else f"de {r['periodo']}"
    if "sem_compras" in r:
        linhas.append(f"**{r['cliente']}**: {r['sem_compras']} na sua loja.")
        return "\n".join(linhas)
    pedidos = r["pedidos"]
    if r["qtd_pedidos"] == 1 and len(pedidos) == 1:
        linhas.append(
            f"**{r['cliente']}** comprou {em}: {_itens(r['qtd_itens'])}, total "
            f"**{moeda(r['total'])}** (pedido {pedidos[0]['numero']})."
        )
        linhas += [
            f"- {i['qtd']}x {i['produto']} ({moeda(i['unit'])} cada)" for i in pedidos[0]["itens"]
        ]
    else:
        linhas.append(
            f"**{r['cliente']}** comprou {em}: {r['qtd_pedidos']} pedidos, "
            f"{_itens(r['qtd_itens'])}, total **{moeda(r['total'])}**."
        )
        for p in pedidos:
            quando = f" em {p['data']}" if p.get("data") else ""
            itens = "; ".join(f"{i['qtd']}x {i['produto']}" for i in p["itens"])
            linhas.append(f"- Pedido {p['numero']}{quando}: {itens}. Total {moeda(p['total'])}")
    if r.get("truncado"):
        linhas.append("Mostrei só parte dos pedidos ou dos itens; o total considera todos.")
    linhas.append(f"Critério: {r['criterio'][:1].lower()}{r['criterio'][1:]}")
    return "\n".join(linhas)


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", str(texto).casefold())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"(?<=\d)[\s.  ](?=\d{3}\b)", "", texto)


def conferir_compras(resposta: str, chamadas: Sequence[ChamadaFeita]) -> str | None:
    """O total do periodo e o de cada pedido mostrado tem de aparecer igual ao da ferramenta; sem
    compras nao pode virar erro, e erro nao pode virar "sem compras"."""
    chamada = next((c for c in reversed(chamadas) if c.nome == "compras_do_cliente"), None)
    if chamada is None:
        return None
    r, texto = chamada.resultado, _normalizar(resposta)
    if "erro" in r or "nao_encontrado" in r:
        return texto_das_compras(r) if "sem compras" in texto else None
    if "sem_compras" in r:
        return None if "sem compras" in texto or "nao comprou" in texto else texto_das_compras(r)
    valores = [r["total"], *(p["total"] for p in r["pedidos"] if len(r["pedidos"]) > 1)]
    numeros = [_normalizar(moeda(v).removeprefix("R$ ")) for v in valores]
    return None if all(n in texto for n in numeros) else texto_das_compras(r)
