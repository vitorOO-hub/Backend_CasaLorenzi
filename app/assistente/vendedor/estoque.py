"""Contagem de estoque do assistente do vendedor: filtros normalizados e soma no SQL.

O modelo so extrai os filtros da pergunta ("roupas", "tam g", "camisas", "preto"). Aqui eles viram
os valores REAIS do catalogo (lidos do banco a cada consulta, nada fixo no codigo) e a soma, a
contagem e o agrupamento acontecem numa query parametrizada. O modelo nunca soma nem varre lista.

Regras do estoque (iguais as telas): so conta quantidade disponivel (> 0) de variacao e produto
ativos, na loja que recebe as vendas do vendedor. O sistema nao tem reserva nem bloqueio de estoque,
e quantidade zero ou negativa nao entra na conta.
"""

import difflib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

PENDENTE = "pendente_identificacao"
LIMITE_DETALHAMENTO = 15
Agrupamento = Literal["nenhum", "tamanho", "categoria", "cor", "produto"]


def normal(texto: Any) -> str:
    texto = unicodedata.normalize("NFKD", str(texto or "").casefold())
    return " ".join("".join(c for c in texto if not unicodedata.combining(c)).split())


# ------------------------------------------------------------------ catalogo real


@dataclass(frozen=True)
class Catalogo:
    tamanhos: tuple[str, ...]
    categorias: tuple[str, ...]  # sem a pendente_identificacao


def catalogo(conexao: Connection) -> Catalogo:
    """Tamanhos e categorias que existem hoje em produtos ativos (a fonte da normalizacao)."""
    tamanhos = conexao.execute(
        text(
            """
            SELECT DISTINCT va.tamanho FROM variacao_produto va
            JOIN produto pr ON pr.id_produto = va.id_produto
            WHERE va.ativa AND pr.ativo AND va.tamanho IS NOT NULL
            """
        )
    ).scalars()
    categorias = conexao.execute(
        text(
            """
            SELECT DISTINCT categoria FROM produto
            WHERE ativo AND categoria IS NOT NULL AND categoria <> :pendente
            """
        ),
        {"pendente": PENDENTE},
    ).scalars()
    return Catalogo(
        tuple(sorted(tamanhos, key=_ordem_do_tamanho)), tuple(sorted(categorias, key=normal))
    )


_GRADE = ["PP", "P", "M", "G", "GG", "XG", "EXG", "U"]


def _ordem_do_tamanho(tamanho: str) -> tuple[int, float, str]:
    if tamanho in _GRADE:
        return (0, _GRADE.index(tamanho), "")
    numero = re.fullmatch(r"\d+(?:[.,]\d+)?", tamanho)
    return (1, float(tamanho.replace(",", ".")), "") if numero else (2, 0, tamanho)


# ------------------------------------------------------------------ normalizacao


# Jeitos de falar o tamanho -> codigo da grade. So vale se o codigo existir no catalogo real.
_SINONIMOS_DE_TAMANHO = {
    "pp": "PP",
    "extra pequeno": "PP",
    "p": "P",
    "pequeno": "P",
    "pequena": "P",
    "m": "M",
    "medio": "M",
    "media": "M",
    "g": "G",
    "grande": "G",
    "gg": "GG",
    "extra grande": "GG",
    "muito grande": "GG",
    "xg": "XG",
    "exg": "EXG",
    "u": "U",
    "unico": "U",
    "tamanho unico": "U",
}
_PREFIXO_DE_TAMANHO = re.compile(r"^(tamanho|tam\.?|tm|numero|num\.?|n\.?|no\.?)\s*")

# Palavras que querem dizer "qualquer peca" (todas as categorias, menos as pendentes).
_TUDO = {
    "roupa",
    "roupas",
    "reoupa",
    "reoupas",
    "peca",
    "pecas",
    "pc",
    "pcs",
    "vestuario",
    "produto",
    "produtos",
    "item",
    "itens",
    "artigo",
    "artigos",
    "tudo",
    "todas",
    "todos",
    "geral",
    "estoque",
}
# Palavras do dia a dia -> categoria real (so vale se a categoria existir no catalogo).
_SINONIMOS_DE_CATEGORIA = {
    "sapato": "calçado",
    "sapatos": "calçado",
    "calcados": "calçado",
    "mocassim": "calçado",
    "bota": "calçado",
    "botas": "calçado",
    "tenis": "calçado",
    "acessorios": "acessório",
    "cinto": "acessório",
    "cintos": "acessório",
    "bolsa": "acessório",
    "bolsas": "acessório",
    "blazer": "alfaiataria",
    "blazers": "alfaiataria",
    "terno": "alfaiataria",
    "casaco": "outerwear",
    "casacos": "outerwear",
    "trench coat": "outerwear",
    "sueter": "tricô",
    "sueteres": "tricô",
    "malha": "tricô",
    "blusa de frio": "moletom",
    "blusao": "moletom",
    "camiseta basica": "camiseta",
    "tshirt": "camiseta",
    "t-shirt": "camiseta",
    "jeans": "calça",
}


@dataclass
class Normalizacao:
    tamanho: str | None = None
    categorias: tuple[str, ...] | None = None  # None = sem filtro de categoria
    tentativas: list[str] = field(default_factory=list)
    invalidos: dict[str, str] = field(default_factory=dict)


def normalizar_tamanho(valor: str, cat: Catalogo, n: Normalizacao) -> None:
    bruto = normal(valor)
    limpo = _PREFIXO_DE_TAMANHO.sub("", bruto).strip()
    codigo = _SINONIMOS_DE_TAMANHO.get(limpo, limpo.upper())
    if codigo in cat.tamanhos:
        n.tamanho = codigo
        if codigo != valor:
            n.tentativas.append(f"tamanho '{valor}' -> {codigo}")
        return
    n.invalidos["tamanho"] = valor
    n.tentativas.append(f"tamanho '{valor}' -> {codigo} (nao existe no catalogo)")


def _sem_plural(palavra: str) -> str:
    for fim, troca in (("oes", "ao"), ("aes", "ao"), ("is", "l"), ("s", "")):
        if palavra.endswith(fim) and len(palavra) > len(fim) + 2:
            return palavra[: -len(fim)] + troca
    return palavra


def normalizar_categoria(valor: str, cat: Catalogo, n: Normalizacao) -> None:
    bruto = normal(valor)
    if bruto in _TUDO or _sem_plural(bruto) in _TUDO:
        n.categorias = cat.categorias
        n.tentativas.append(f"categoria '{valor}' -> todas (menos pendentes de identificacao)")
        return
    por_nome = {normal(c): c for c in cat.categorias}
    candidatos = [bruto, _sem_plural(bruto)]
    for candidato in candidatos:
        real = por_nome.get(candidato) or _SINONIMOS_DE_CATEGORIA.get(candidato)
        if real and real in cat.categorias:
            n.categorias = (real,)
            if real != valor:
                n.tentativas.append(f"categoria '{valor}' -> {real}")
            return
    # Erro de digitacao ("camsias"): o nome real mais parecido, se for bem parecido.
    parecido = difflib.get_close_matches(_sem_plural(bruto), list(por_nome), n=1, cutoff=0.75)
    if parecido:
        n.categorias = (por_nome[parecido[0]],)
        n.tentativas.append(f"categoria '{valor}' -> {por_nome[parecido[0]]} (parecida)")
        return
    n.invalidos["categoria"] = valor
    n.tentativas.append(f"categoria '{valor}' (nao existe no catalogo)")


# ------------------------------------------------------------------ consulta


@dataclass(frozen=True)
class Filtro:
    id_loja: UUID
    tamanho: str | None = None
    categorias: tuple[str, ...] | None = None
    cor: str | None = None
    marca: str | None = None
    produto: str | None = None


_COLUNA = {
    "tamanho": "va.tamanho",
    "categoria": "pr.categoria",
    "cor": "va.cor",
    "produto": "pr.nome",
}


# A extensao unaccent nao esta instalada: a mesma normalizacao de `normal`, em SQL.
_COM_ACENTO = "ÁÀÂÃÄáàâãäÉÈÊËéèêëÍÌÎÏíìîïÓÒÔÕÖóòôõöÚÙÛÜúùûüÇç"
_SEM_ACENTO = "AAAAAaaaaaEEEEeeeeIIIIiiiiOOOOOoooooUUUUuuuuCc"


def _sem_acento(coluna: str) -> str:
    return f"lower(translate({coluna}, '{_COM_ACENTO}', '{_SEM_ACENTO}'))"


def _condicoes(f: Filtro) -> tuple[str, dict[str, Any]]:
    condicoes = ["e.id_loja = :loja", "e.quantidade > 0", "va.ativa", "pr.ativo"]
    parametros: dict[str, Any] = {"loja": str(f.id_loja)}
    if f.tamanho:
        # Igualdade exata: "G" nunca casa com "GG".
        condicoes.append("va.tamanho = :tamanho")
        parametros["tamanho"] = f.tamanho
    if f.categorias is not None:
        condicoes.append("pr.categoria = ANY(:categorias)")
        parametros["categorias"] = list(f.categorias)
    # Texto do vendedor so entra como parametro (LIKE), nunca no SQL.
    if f.cor:
        condicoes.append(f"{_sem_acento('va.cor')} LIKE :cor")
        parametros["cor"] = f"%{normal(f.cor)}%"
    if f.marca:
        condicoes.append(f"{_sem_acento('pr.marca')} LIKE :marca")
        parametros["marca"] = f"%{normal(f.marca)}%"
    for i, palavra in enumerate(normal(f.produto).split() if f.produto else []):
        if len(palavra) > 1 and palavra not in {"de", "da", "do", "com", "e"}:
            condicoes.append(f"{_sem_acento("pr.nome || ' ' || va.sku")} LIKE :p{i}")
            parametros[f"p{i}"] = f"%{palavra}%"
    return " AND ".join(condicoes), parametros


_BASE = """
    FROM estoque e
    JOIN variacao_produto va ON va.id_variacao = e.id_variacao
    JOIN produto pr ON pr.id_produto = va.id_produto
    WHERE {condicoes}
"""


def contar(conexao: Connection, f: Filtro, agrupar_por: Agrupamento) -> dict[str, Any]:
    condicoes, parametros = _condicoes(f)
    base = _BASE.format(condicoes=condicoes)  # nosec B608: so colunas fixas
    totais = (
        conexao.execute(
            text(
                f"""
                SELECT COALESCE(sum(e.quantidade), 0)::int AS unidades,
                       count(DISTINCT pr.id_produto)::int AS modelos,
                       count(DISTINCT va.id_variacao)::int AS skus
                {base}
                """  # nosec B608
            ),
            parametros,
        )
        .mappings()
        .one()
    )
    detalhamento: list[dict[str, Any]] = []
    total_grupos = 0
    if agrupar_por != "nenhum":
        coluna = _COLUNA[agrupar_por]
        linhas = (
            conexao.execute(
                text(
                    f"""
                    SELECT {coluna} AS valor,
                           sum(e.quantidade)::int AS unidades,
                           count(DISTINCT pr.id_produto)::int AS modelos,
                           count(*) OVER ()::int AS grupos
                    {base}
                    GROUP BY {coluna}
                    ORDER BY unidades DESC, valor
                    LIMIT :limite
                    """  # nosec B608
                ),
                {**parametros, "limite": LIMITE_DETALHAMENTO},
            )
            .mappings()
            .all()
        )
        total_grupos = linhas[0]["grupos"] if linhas else 0
        detalhamento = [
            {agrupar_por: l["valor"], "unidades": l["unidades"], "modelos": l["modelos"]}
            for l in linhas  # noqa: E741
        ]
    return {
        "unidades": totais["unidades"],
        "modelos": totais["modelos"],
        "skus": totais["skus"],
        "detalhamento": detalhamento,
        "truncado": total_grupos > len(detalhamento),
    }
