"""Respostas e entradas da gestao do admin (time interno). Nunca expoe cliente nem ids do Auth."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

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


# ---------------------------------------------------------------- catalogo

TextoCurto = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]


class NovaPeca(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
    nome: TextoCurto
    categoria: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
    ]
    preco: Annotated[Decimal, Field(ge=0, le=Decimal("9999999.99"), decimal_places=2)]


class PecaAlterada(BaseModel):
    """Campo ausente = nao muda. O preco vale para todas as variacoes da peca."""

    model_config = ConfigDict(extra="forbid")

    nome: TextoCurto | None = None
    categoria: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
        | None
    ) = None
    preco: Annotated[Decimal, Field(ge=0, le=Decimal("9999999.99"), decimal_places=2)] | None = None

    @model_validator(mode="after")
    def _algo_para_mudar(self) -> "PecaAlterada":
        if self.nome is None and self.categoria is None and self.preco is None:
            raise ValueError("Informe o que mudar")
        return self


class PecaDoCatalogo(Saida):
    id_produto: UUID
    nome: str
    categoria: str | None
    preco: float
    skus: list[str]
    variacoes: int
    estoque_rede: int


class Catalogo(Saida):
    total: int
    itens: list[PecaDoCatalogo]


class PecaExcluida(Saida):
    id_produto: UUID
    excluido: bool


# ---------------------------------------------------------------- auditoria


class RegistroDeAuditoria(Saida):
    id_auditoria: UUID
    data: datetime
    autor: str
    acao: str
    detalhe: str


class Auditoria(Saida):
    total: int
    itens: list[RegistroDeAuditoria]


# ---------------------------------------------------------------- integracoes


class LoteImportado(Saida):
    codigo: str
    origem: str
    recebido_em: datetime
    registros: int
    pendentes: int
    # pendente_mapeamento | processado | com_erro
    situacao: str


class RegistroImportado(Saida):
    id_registro: UUID
    lote: str
    descricao_externa: str
    codigo_externo: str
    sku_mapeado: str | None


class SkuParaMapear(Saida):
    id_variacao: UUID
    sku: str
    nome: str


class Integracoes(Saida):
    lotes: list[LoteImportado]
    registros: list[RegistroImportado]
    skus: list[SkuParaMapear]


class MapeamentoDeRegistro(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id_variacao: UUID
