"""Respostas e entradas da gestao do admin (time interno). Nunca expoe cliente nem ids do Auth."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

Cargo = Literal["atendente", "operador_estoque", "gerente_loja", "admin"]


class Saida(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UsuarioDaEquipe(Saida):
    id_usuario: UUID
    nome: str
    email: str
    cargo: str
    id_loja: UUID | None
    loja_nome: str | None
    ativo: bool
    # A conta ja esta ligada a um login do Supabase (a pessoa consegue entrar).
    com_acesso: bool
    criado_em: datetime


class OpcaoDeCargo(Saida):
    codigo: str
    nome: str


class OpcaoDeLoja(Saida):
    id_loja: UUID
    nome: str


class OpcoesDaEquipe(Saida):
    cargos: list[OpcaoDeCargo]
    lojas: list[OpcaoDeLoja]


class Equipe(Saida):
    total: int
    itens: list[UsuarioDaEquipe]
    opcoes: OpcoesDaEquipe


class MudancaDeUsuario(BaseModel):
    """So o que a tela altera: cargo, unidade e acesso. Campo ausente = nao muda."""

    model_config = ConfigDict(extra="forbid")

    cargo: Cargo | None = None
    id_loja: UUID | None = None
    ativo: bool | None = None
