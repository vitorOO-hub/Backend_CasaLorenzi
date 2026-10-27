"""Horario de funcionamento da loja (`loja.horario_funcionamento`, jsonb).

Formato: um objeto com os dias `seg`..`dom`; cada dia e `{abre, fecha}` em HH:MM ou `null`
(fechada). Lido pelo site, pelo assistente do cliente e editado pelo admin.
"""

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
