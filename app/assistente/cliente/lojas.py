"""Qual loja o cliente citou na conversa e se a equipe esta no horario.

Reconhecimento por regra, sobre o que o CLIENTE escreveu (nao sobre o texto do modelo): cada loja
e reconhecida pela parte do nome que a distingue ("vulto batel" -> "batel"; o e-commerce por
"site", "online" etc.). Se mais de uma loja casar, a marca citada desempata; se ainda sobrar
duvida, nenhuma loja e escolhida e o chamado vai para a fila geral, que todos os atendentes veem.

Os horarios sao os do cadastro de cada loja (`loja.horario_funcionamento`), os mesmos que o site e
o assistente do vendedor mostram.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from app.core.horario import DIAS, NOMES_DOS_DIAS, aberta, proxima_abertura

# Palavras que nao distinguem uma loja da outra.
GENERICAS = frozenset(
    {"casa", "lorenzi", "vulto", "loja", "lojas", "de", "da", "do", "e", "ecommerce"}
)
# Como o cliente fala do canal online (a loja "e-commerce casa lorenzi").
ONLINE = frozenset({"site", "online", "ecommerce", "internet", "virtual"})
# Canais que nao atendem cliente: centro de distribuicao e canais antigos da Vulto.
FORA_DO_ATENDIMENTO = ("cd", "centro de distribuicao", "vulto app", "vulto ecommerce")


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto.casefold())
    texto = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return re.sub(r"e-?commerce", "ecommerce", texto)


def _palavras(texto: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", _normalizar(texto)))


@dataclass(frozen=True)
class Candidata:
    id_loja: UUID
    nome: str
    marca: str | None
    chaves: frozenset[str]
    online: bool
    horario: dict | None


def candidatas(lojas: list[dict[str, Any]]) -> list[Candidata]:
    """Lojas que atendem cliente, com as palavras que as distinguem."""
    resultado = []
    for loja in lojas:
        nome = " ".join(_normalizar(str(loja["nome"])).split())
        if any(nome == f or nome.startswith(f"{f} ") for f in FORA_DO_ATENDIMENTO):
            continue
        online = "ecommerce" in nome
        marca = "vulto" if nome.startswith("vulto") else "lorenzi" if "lorenzi" in nome else None
        chaves = frozenset(_palavras(nome) - GENERICAS)
        if not chaves and not online:
            continue  # "casa lorenzi" ou "vulto" sozinhos: nao apontam uma loja
        resultado.append(
            Candidata(
                id_loja=UUID(str(loja["id_loja"])),
                nome=str(loja["nome"]),
                marca=marca,
                chaves=chaves,
                online=online,
                horario=loja.get("horario_funcionamento"),
            )
        )
    return resultado


def identificar(textos_do_cliente: list[str], lojas: list[dict[str, Any]]) -> Candidata | None:
    """A loja de que o cliente esta falando, ou None (nenhuma ou mais de uma)."""
    palavras = (
        set().union(*(_palavras(t) for t in textos_do_cliente)) if textos_do_cliente else set()
    )
    achadas = [
        c
        for c in candidatas(lojas)
        if (c.online and palavras & ONLINE) or (c.chaves and c.chaves <= palavras)
    ]
    # Mesmo bairro em duas marcas ("vulto batel" e "casa lorenzi batel"): a marca citada decide.
    # O desempate vale so entre lojas com as mesmas chaves; loja citada pelo nome nao sai.
    marcas = {m for m in ("vulto", "lorenzi") if m in palavras}
    if len(marcas) == 1:
        por_chave: dict[frozenset[str], list[Candidata]] = {}
        for c in achadas:
            por_chave.setdefault(c.chaves, []).append(c)
        achadas = [
            c
            for grupo in por_chave.values()
            for c in (grupo if len(grupo) == 1 else [c for c in grupo if c.marca in marcas])
        ]
    return achadas[0] if len(achadas) == 1 else None


def aviso_fora_do_horario(
    lojas: list[dict[str, Any]], agora: datetime, id_loja: UUID | None = None
) -> str | None:
    """Texto para o cliente quando ninguem da equipe esta em horario agora.

    Chamado de uma loja: vale o horario dela. Fila geral: basta uma loja aberta. Sem horario
    cadastrado, nao ha aviso (nao da para afirmar nada).
    """
    relevantes = [c for c in candidatas(lojas) if id_loja is None or c.id_loja == id_loja]
    com_horario = [c for c in relevantes if c.horario]
    if not com_horario or any(aberta(c.horario, agora) for c in com_horario):
        return None
    aberturas = [a for c in com_horario if (a := proxima_abertura(c.horario, agora))]
    if not aberturas:
        return None
    volta = min(aberturas)
    dias = (volta.date() - agora.date()).days
    quando = (
        "hoje"
        if dias == 0
        else "amanhã"
        if dias == 1
        else f"na {NOMES_DOS_DIAS[DIAS[volta.weekday()]]}"
        if volta.weekday() < 5
        else f"no {NOMES_DOS_DIAS[DIAS[volta.weekday()]]}"
    )
    return (
        f"Nossa equipe está fora do horário de atendimento agora e responde {quando} a partir "
        f"das {volta.strftime('%H:%M')}."
    )
