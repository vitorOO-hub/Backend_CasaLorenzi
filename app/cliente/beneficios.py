"""Benefícios das categorias do Lorenzi+ (bronze, prata, ouro e black).

Fonte única da regra: o back aplica o frete grátis no checkout e manda a lista de benefícios para a
aba Lorenzi+ do cliente e para a ficha do painel.

- Prata: frete grátis nas compras a partir de R$ 600 em peças.
- Ouro: frete grátis em qualquer compra e acesso antecipado às coleções.
- Black: frete grátis em qualquer compra, acesso antecipado às coleções e serviço de ajuste como
  cortesia.

Fora das categorias vale a regra da loja: frete grátis a partir de R$ 1.000 em peças.
"""

from decimal import Decimal
from typing import Any

FRETE_GRATIS_DA_LOJA = Decimal("1000")

_TEXTOS = {
    "frete_600": (
        "Frete grátis acima de R$ 600",
        "Entrega em casa sem custo nas compras a partir de R$ 600 em peças.",
    ),
    "frete_sempre": (
        "Frete grátis em qualquer compra",
        "Entrega em casa sem custo, qualquer que seja o valor.",
    ),
    "acesso_antecipado": (
        "Acesso antecipado às coleções",
        "Você conhece e compra as novas coleções antes da abertura ao público.",
    ),
    "ajuste_cortesia": (
        "Serviço de ajuste como cortesia",
        "Ajustes de alfaiataria nas suas peças por nossa conta, em qualquer uma das casas.",
    ),
}

_POR_CATEGORIA: dict[str, tuple[str, ...]] = {
    "bronze": (),
    "prata": ("frete_600",),
    "ouro": ("frete_sempre", "acesso_antecipado"),
    "black": ("frete_sempre", "acesso_antecipado", "ajuste_cortesia"),
}

_FRETE_GRATIS_A_PARTIR: dict[str, Decimal] = {
    "prata": Decimal("600"),
    "ouro": Decimal("0"),
    "black": Decimal("0"),
}


def beneficios(categoria: str | None) -> list[dict[str, Any]]:
    """Os benefícios da categoria, na ordem em que aparecem para o cliente."""
    return [
        {"codigo": codigo, "titulo": _TEXTOS[codigo][0], "descricao": _TEXTOS[codigo][1]}
        for codigo in _POR_CATEGORIA.get(categoria or "", ())
    ]


def frete_gratis_a_partir(categoria: str | None) -> Decimal:
    """Valor em peças a partir do qual a entrega sai de graça (0 = sempre)."""
    return _FRETE_GRATIS_A_PARTIR.get(categoria or "", FRETE_GRATIS_DA_LOJA)


def frete_com_beneficio(categoria: str | None, frete: Decimal, valor_das_pecas: Decimal) -> Decimal:
    """O frete que o cliente paga: zero quando a categoria (ou a regra da loja) dá frete grátis."""
    if valor_das_pecas >= frete_gratis_a_partir(categoria):
        return Decimal("0.00")
    return frete
