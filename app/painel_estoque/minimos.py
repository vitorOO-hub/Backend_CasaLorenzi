"""Estoque minimo por peca e loja: abaixo dele a peca aparece como "estoque baixo".

Ver e ajustar e coisa da gestao (gerente da loja e admin). O gerente mexe so na propria loja;
o admin informa a loja. As escritas acontecem numa transacao: ou todos os minimos mudam, ou nenhum.
"""

from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.papeis import UsuarioAtual
from app.gestao import auditoria
from app.painel_estoque import service, service_escrita
from app.painel_estoque.erros import LojaObrigatoria, PecaNaoEncontrada

PAPEIS = service_escrita.PAPEIS_DA_GESTAO
MAXIMO_DE_ITENS = 200

Sku = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]


class NovoMinimo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: Sku
    minimo: int = Field(ge=0, le=100_000, strict=True)


class DefinirMinimos(BaseModel):
    model_config = ConfigDict(extra="forbid")

    itens: list[NovoMinimo] = Field(min_length=1, max_length=MAXIMO_DE_ITENS)
    id_loja: UUID | None = None

    @model_validator(mode="after")
    def _sem_peca_repetida(self) -> "DefinirMinimos":
        skus = [i.sku for i in self.itens]
        if len(set(skus)) != len(skus):
            raise ValueError("peca repetida")
        return self


class ItemMinimo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id_variacao: UUID
    sku: str
    produto: str
    cor: str
    tamanho: str
    saldo: int
    minimo: int


class Minimos(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id_loja: UUID
    loja_nome: str
    total: int
    itens: list[ItemMinimo]


class Atualizados(BaseModel):
    model_config = ConfigDict(extra="forbid")

    atualizados: int


LISTA = """
FROM estoque e
JOIN variacao_produto v ON v.id_variacao = e.id_variacao AND v.ativa
JOIN produto ON produto.id_produto = v.id_produto AND produto.ativo
WHERE e.id_loja = CAST(:id_loja AS uuid)
  AND (CAST(:busca AS text) IS NULL
       OR strpos(lower(produto.nome || ' ' || v.sku), lower(CAST(:busca AS text))) > 0)
"""
SELECAO = """
SELECT v.id_variacao, v.sku, produto.nome AS produto, v.cor, v.tamanho,
       e.quantidade AS saldo, e.estoque_minimo AS minimo
"""
PAGINA = " ORDER BY produto.nome, v.cor, v.tamanho, v.sku LIMIT :limite OFFSET :deslocamento"
SQL_ITENS = SELECAO + LISTA + PAGINA  # nosec B608
SQL_TOTAL = "SELECT count(*) " + LISTA  # nosec B608


def _loja_da_gestao(usuario: UsuarioAtual, id_loja: UUID | None) -> UUID:
    loja = service.loja_do_escopo(usuario, id_loja)
    if loja is None:
        raise LojaObrigatoria()
    return loja


def listar(
    conexao: Connection,
    usuario: UsuarioAtual,
    *,
    id_loja: UUID | None,
    busca: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    loja = _loja_da_gestao(usuario, id_loja)
    nome = conexao.execute(
        text("SELECT nome FROM loja WHERE id_loja = CAST(:id AS uuid)"), {"id": str(loja)}
    ).scalar()
    parametros = {"id_loja": str(loja), "busca": busca}
    total = conexao.execute(text(SQL_TOTAL), parametros).scalar_one()
    itens = conexao.execute(
        text(SQL_ITENS), {**parametros, "limite": limit, "deslocamento": offset}
    ).mappings()
    return {
        "id_loja": loja,
        "loja_nome": nome or "",
        "total": int(total),
        "itens": [dict(i) for i in itens],
    }


def definir(conexao: Connection, usuario: UsuarioAtual, dados: DefinirMinimos) -> dict[str, int]:
    """Atualiza todos os minimos de uma vez; peca que a loja nao mantem desfaz tudo (404)."""
    loja = _loja_da_gestao(usuario, dados.id_loja)
    atualizados = conexao.execute(
        text(
            """
            WITH novo AS (
                SELECT * FROM unnest(CAST(:skus AS text[]), CAST(:minimos AS int[]))
                    AS n(sku, minimo)
            )
            UPDATE estoque e
            SET estoque_minimo = novo.minimo, atualizado_em = now()
            FROM novo, variacao_produto v
            WHERE v.sku = novo.sku
              AND e.id_variacao = v.id_variacao
              AND e.id_loja = CAST(:id_loja AS uuid)
            RETURNING v.sku
            """
        ),
        {
            "skus": [i.sku for i in dados.itens],
            "minimos": [i.minimo for i in dados.itens],
            "id_loja": str(loja),
        },
    ).fetchall()
    if len(atualizados) != len(dados.itens):
        conexao.rollback()
        raise PecaNaoEncontrada()
    auditoria.registrar(
        conexao, usuario, "Definiu estoque mínimo", f"{len(atualizados)} peça(s) da unidade"
    )
    conexao.commit()
    return {"atualizados": len(atualizados)}
