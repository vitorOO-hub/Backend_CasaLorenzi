"""Papeis internos e o usuario autenticado, como o backend os enxerga a partir do JWT."""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class Papel(StrEnum):
    ATENDENTE = "atendente"
    OPERADOR_ESTOQUE = "operador_estoque"
    GERENTE_LOJA = "gerente_loja"
    ADMIN = "admin"


# Papeis que pertencem a uma loja (CLAUDE.md, secao 3). Admin tem loja nula; cliente nao tem papel.
PAPEIS_COM_LOJA = frozenset({Papel.ATENDENTE, Papel.OPERADOR_ESTOQUE, Papel.GERENTE_LOJA})


class UsuarioAtual(BaseModel):
    """Usuario do token. Cliente tem `papel=None`; admin tem `id_loja=None`."""

    model_config = ConfigDict(frozen=True)

    id_auth: UUID
    papel: Papel | None = None
    id_loja: UUID | None = None

    def pode_acessar_loja(self, id_loja: UUID) -> bool:
        if self.papel is Papel.ADMIN:
            return True
        return self.papel in PAPEIS_COM_LOJA and self.id_loja == id_loja
