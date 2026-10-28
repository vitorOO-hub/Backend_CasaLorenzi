"""Politicas oficiais da loja, lidas de `politicas.md` (a unica fonte do assistente sobre elas).

O documento tem um tema por secao (`## codigo | Titulo`). A ferramenta `consultar_politica` devolve
o texto da secao; tema marcado como PENDENTE vira orientacao de passar para a equipe.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

ARQUIVO = Path(__file__).with_name("politicas.md")
CABECALHO = re.compile(r"^## ([a-z_]+) \| (.+)$")


@dataclass(frozen=True)
class Politica:
    codigo: str
    titulo: str
    texto: str

    @property
    def pendente(self) -> bool:
        return "PENDENTE" in self.texto


def ler(conteudo: str) -> dict[str, Politica]:
    politicas: dict[str, Politica] = {}
    atual: tuple[str, str] | None = None
    linhas: list[str] = []

    def fechar() -> None:
        if atual:
            politicas[atual[0]] = Politica(atual[0], atual[1], "\n".join(linhas).strip())

    for linha in conteudo.splitlines():
        if linha.startswith("## "):
            fechar()
            achou = CABECALHO.match(linha.strip())
            if not achou:
                raise ValueError(f"cabecalho de politica fora do formato: {linha!r}")
            atual, linhas = (achou.group(1), achou.group(2).strip()), []
        elif atual:
            linhas.append(linha)
    fechar()
    return politicas


@cache
def todas() -> dict[str, Politica]:
    return ler(ARQUIVO.read_text(encoding="utf-8"))
