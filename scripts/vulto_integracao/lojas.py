"""Traduz IDs numericos de loja do Vulto para os UUIDs da tabela `loja`."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import TypeVar

T = TypeVar("T")

CODIGO_LOJA_POR_ID_VULTO = MappingProxyType(
    {
        1: "LOJA-VULTO-PINHEIROS",
        2: "LOJA-VULTO-SHOPPING-ELDORADO",
        3: "LOJA-VULTO-SAVASSI",
        4: "LOJA-VULTO-BATEL",
        5: "LOJA-VULTO-E-COMMERCE",
        6: "LOJA-VULTO-APP",
        7: "LOJA-CD-CAJAMAR",
    }
)


def resolver_id_loja_vulto(
    loja_id_vulto: int, lojas_por_codigo: Mapping[str, T]
) -> T:
    """Resolve o ID legado ao ID da linha correspondente em `public.loja`."""
    if isinstance(loja_id_vulto, bool) or not isinstance(loja_id_vulto, int):
        raise ValueError(f"loja_id do Vulto deve ser inteiro: {loja_id_vulto!r}")

    codigo = CODIGO_LOJA_POR_ID_VULTO.get(loja_id_vulto)
    if codigo is None:
        raise ValueError(f"loja_id do Vulto sem mapeamento: {loja_id_vulto}")

    try:
        return lojas_por_codigo[codigo]
    except KeyError as erro:
        raise ValueError(
            f"A loja {codigo} (loja_id Vulto {loja_id_vulto}) nao existe em public.loja"
        ) from erro
