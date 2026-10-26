"""Respostas e entradas da gestao do admin (time interno). Nunca expoe ids do Auth; cliente so
aparece na fila de vendas pendentes (nome do cliente sugerido para a venda, sem documento)."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.core.padroes import texto_padrao

Cargo = Literal["atendente", "operador_estoque", "vendedor", "gerente_loja", "admin"]


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


class NovoUsuarioDaEquipe(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nome: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=160)]
    email: EmailStr
    cargo: Cargo
    id_loja: UUID | None = None

    @field_validator("nome")
    @classmethod
    def _nome_padrao(cls, valor: str) -> str:
        return texto_padrao(valor) or valor

    @field_validator("email")
    @classmethod
    def _email_padrao(cls, valor: EmailStr) -> str:
        return str(valor).strip().lower()


# ---------------------------------------------------------------- catalogo

TextoCurto = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]


def _padrao(valor: str) -> str:
    return texto_padrao(valor) or valor


# Nome e categoria da peca seguem o padrao do banco (minusculas, um espaco entre palavras).
NomeDaPeca = Annotated[TextoCurto, AfterValidator(_padrao)]
Categoria = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
    AfterValidator(_padrao),
]


class NovaPeca(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
    nome: NomeDaPeca
    categoria: Categoria
    preco: Annotated[Decimal, Field(ge=0, le=Decimal("9999999.99"), decimal_places=2)]


class PecaAlterada(BaseModel):
    """Campo ausente = nao muda. O preco vale para todas as variacoes da peca."""

    model_config = ConfigDict(extra="forbid")

    nome: NomeDaPeca | None = None
    categoria: Categoria | None = None
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


class VendaImportacaoPendente(Saida):
    id_venda_pendente: UUID
    venda_id_origem: str
    status_origem: str | None
    motivos: list[str]
    quantidade_itens: int
    criada_em: datetime
    estado: Literal["pendente", "importada", "descartada"] = "pendente"
    resolvida_em: datetime | None = None


class GrupoDeMotivo(Saida):
    grupo: str
    vendas: int


class VendasImportacaoPendentes(Saida):
    total: int
    itens: list[VendaImportacaoPendente]
    por_grupo: list[GrupoDeMotivo] = []


class VariacaoSugerida(Saida):
    id_variacao: UUID
    sku: str
    nome: str


class ItemDaVendaPendente(Saida):
    sku_origem: str
    descricao: str | None
    quantidade: int
    preco_unitario: Decimal | None
    variacao_sugerida: VariacaoSugerida | None


class ClienteSugerido(Saida):
    id_cliente: UUID
    nome: str


class VendaPendenteDetalhe(Saida):
    """O que serve para resolver a venda. Sem CPF, telefone nem e-mail (so o fim do CPF)."""

    id_venda_pendente: UUID
    venda_id_origem: str
    estado: Literal["pendente", "importada", "descartada"]
    motivos: list[str]
    status_origem: str | None
    resolvida_em: datetime | None
    observacao_resolucao: str | None
    loja: str | None
    canal: str | None
    status_destino: str | None
    vendida_em: datetime | None
    vendedor: str | None
    total: Decimal | None
    frete: Decimal
    desconto: Decimal
    total_calculado: Decimal | None
    situacao_valores: str
    cpf_final: str | None
    sugestao_cliente: ClienteSugerido | None
    itens: list[ItemDaVendaPendente]


Justificativa = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=3, max_length=300)
]


class DescarteDeVenda(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observacao: Justificativa


class ItemImportado(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id_variacao: UUID
    quantidade: int = Field(gt=0, le=999)
    preco_unitario: Decimal = Field(ge=0, max_digits=12, decimal_places=2)


class ImportacaoDeVenda(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id_cliente: UUID
    valor_total: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    valor_frete: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)
    itens: list[ItemImportado] = Field(min_length=1, max_length=100)
    observacao: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None = (
        None
    )


class MapeamentoDeRegistro(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id_variacao: UUID
