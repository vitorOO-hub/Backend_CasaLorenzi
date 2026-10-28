"""Horario de funcionamento da loja (`loja.horario_funcionamento`, jsonb).

Formato: um objeto com os dias `seg`..`dom`; cada dia e `{abre, fecha}` em HH:MM ou `null`
(fechada). Lido pelo site, pelo assistente do cliente e editado pelo admin.
"""

from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field, model_validator

DIAS = ("seg", "ter", "qua", "qui", "sex", "sab", "dom")
HORA = r"^([01]\d|2[0-3]):[0-5]\d$"


class Turno(BaseModel):
    model_config = ConfigDict(extra="forbid")

    abre: str = Field(pattern=HORA)
    fecha: str = Field(pattern=HORA)

    @model_validator(mode="after")
    def _fecha_depois(self) -> "Turno":
        if self.fecha <= self.abre:
            raise ValueError("O horario de fechar precisa ser depois do de abrir")
        return self


class HorarioFuncionamento(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seg: Turno | None = None
    ter: Turno | None = None
    qua: Turno | None = None
    qui: Turno | None = None
    sex: Turno | None = None
    sab: Turno | None = None
    dom: Turno | None = None


NOMES_DOS_DIAS = {
    "seg": "segunda",
    "ter": "terça",
    "qua": "quarta",
    "qui": "quinta",
    "sex": "sexta",
    "sab": "sábado",
    "dom": "domingo",
}


def descrever(horario: dict | None) -> str | None:
    """'seg 10:00-19:00, ..., dom fechada', como no assistente do vendedor. None = sem cadastro."""
    if not horario:
        return None
    partes = []
    for dia in DIAS:
        turno = horario.get(dia)
        partes.append(f"{dia} {turno['abre']}-{turno['fecha']}" if turno else f"{dia} fechada")
    return ", ".join(partes)


def aberta(horario: dict | None, agora: datetime) -> bool:
    """`agora` no fuso da loja (America/Sao_Paulo)."""
    turno = (horario or {}).get(DIAS[agora.weekday()])
    return bool(turno) and turno["abre"] <= agora.strftime("%H:%M") < turno["fecha"]


def proxima_abertura(horario: dict | None, agora: datetime) -> datetime | None:
    """Quando a loja abre de novo (hoje mais tarde ou num dos proximos 7 dias). None sem horario."""
    if not horario:
        return None
    for adiante in range(8):
        dia = agora + timedelta(days=adiante)
        turno = horario.get(DIAS[dia.weekday()])
        if not turno:
            continue
        hora, minuto = (int(p) for p in turno["abre"].split(":"))
        abre = dia.replace(hour=hora, minute=minuto, second=0, microsecond=0)
        if abre > agora:
            return abre
    return None
