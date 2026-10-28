"""Datas faladas pelo vendedor ("ontem", "dia 15", "15/10", "semana passada") viram dias de verdade.

A conta e do backend, no fuso de Sao Paulo e com a data de hoje: o modelo so repassa o texto como o
vendedor falou. Sem ano, vale o ano corrente; se o dia ainda nao chegou neste ano, vale o ano
anterior e o `aviso` diz isso na resposta. O que nao der para entender volta `None` (quem chama pede
o dia ao vendedor, sem chamar o modelo).
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta

MESES = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}
_MES = "(" + "|".join(MESES) + ")"


def _normal(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.casefold())
    return " ".join("".join(c for c in texto if not unicodedata.combining(c)).split())


def dia(d: date) -> str:
    return d.strftime("%d/%m/%Y")


@dataclass(frozen=True)
class Periodo:
    inicio: date
    fim: date
    aviso: str | None = None

    @property
    def rotulo(self) -> str:
        if self.inicio == self.fim:
            return dia(self.inicio)
        return f"{dia(self.inicio)} a {dia(self.fim)}"


def _ano(n: str | None) -> int | None:
    if not n:
        return None
    return int(n) + 2000 if len(n) == 2 else int(n)


def _dia_sem_ano(d: int, m: int, ano: int | None, hoje: date) -> Periodo | None:
    try:
        if ano is not None:
            return Periodo(date(ano, m, d), date(ano, m, d))
        escolhido = date(hoje.year, m, d)
        if escolhido <= hoje:
            return Periodo(escolhido, escolhido)
        anterior = date(hoje.year - 1, m, d)
    except ValueError:
        return None
    aviso = f"Considerei {dia(anterior)} (ano passado), porque {dia(escolhido)} ainda não chegou."
    return Periodo(anterior, anterior, aviso)


def _mes_inteiro(m: int, ano: int | None, hoje: date) -> Periodo:
    aviso = None
    if ano is None:
        ano = hoje.year
        if date(ano, m, 1) > hoje:
            ano -= 1
            aviso = f"Considerei o mês de {ano} (ano passado), porque esse mês ainda não chegou."
    inicio = date(ano, m, 1)
    fim = (date(ano + (m == 12), m % 12 + 1, 1)) - timedelta(days=1)
    return Periodo(inicio, min(fim, hoje) if inicio <= hoje else fim, aviso)


def resolver(texto: str, hoje: date) -> Periodo | None:
    t = _normal(texto)
    if re.search(r"\banteontem\b", t):
        return Periodo(hoje - timedelta(days=2), hoje - timedelta(days=2))
    if re.search(r"\bontem\b", t):
        return Periodo(hoje - timedelta(days=1), hoje - timedelta(days=1))
    if re.search(r"\bhoje\b", t):
        return Periodo(hoje, hoje)

    # O proprio rotulo de um periodo ("01/10/2026 a 31/10/2026"), que o backend repassa.
    if achado := re.search(r"\b(\d{2})/(\d{2})/(\d{4}) a (\d{2})/(\d{2})/(\d{4})\b", t):
        try:
            d1, m1, a1, d2, m2, a2 = (int(x) for x in achado.groups())
            return Periodo(date(a1, m1, d1), date(a2, m2, d2))
        except ValueError:
            return None
    if achado := re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t):
        a, m, d = (int(x) for x in achado.groups())
        return _dia_sem_ano(d, m, a, hoje)
    if achado := re.search(r"\b(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{4}|\d{2}))?\b", t):
        return _dia_sem_ano(int(achado[1]), int(achado[2]), _ano(achado[3]), hoje)
    if achado := re.search(rf"\b(\d{{1,2}})\s+de\s+{_MES}(?:\s+de\s+(\d{{4}}))?\b", t):
        return _dia_sem_ano(int(achado[1]), MESES[achado[2]], _ano(achado[3]), hoje)

    if re.search(r"\bsemana passada\b", t):
        segunda = hoje - timedelta(days=hoje.weekday() + 7)
        return Periodo(segunda, segunda + timedelta(days=6))
    if re.search(r"\b(esta|essa|nesta|nessa) semana\b", t):
        return Periodo(hoje - timedelta(days=hoje.weekday()), hoje)
    if re.search(r"\bmes passado\b", t):
        ultimo = hoje.replace(day=1) - timedelta(days=1)
        return Periodo(ultimo.replace(day=1), ultimo)
    if re.search(r"\b(este|esse|neste|nesse) mes\b", t):
        return Periodo(hoje.replace(day=1), hoje)
    if achado := re.search(rf"\b{_MES}(?:\s+de\s+(\d{{4}}))?\b", t):
        return _mes_inteiro(MESES[achado[1]], _ano(achado[2]), hoje)

    # "dia 15" sem mes: o mes corrente; se o dia ainda nao chegou, o mes anterior.
    if achado := re.search(r"\bdia\s+(\d{1,2})\b", t):
        d = int(achado[1])
        try:
            escolhido = hoje.replace(day=d)
        except ValueError:
            escolhido = None
        if escolhido is not None and escolhido <= hoje:
            return Periodo(escolhido, escolhido)
        mes_anterior = hoje.replace(day=1) - timedelta(days=1)
        try:
            anterior = mes_anterior.replace(day=d)
        except ValueError:
            return None
        return Periodo(
            anterior,
            anterior,
            f"Considerei {dia(anterior)} (mês passado), porque o dia {d} deste mês ainda não "
            "chegou.",
        )
    return None
