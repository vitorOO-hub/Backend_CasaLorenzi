"""Resolve aliases estruturados do catalogo Vulto sem alterar o SKU de origem."""

import re
from collections.abc import Mapping

COR_REDUZIDA = {
    "Y": "AMA",
    "A": "AZM",
    "G": "BEG",
    "B": "BRA",
    "C": "CIN",
    "J": "JCL",
    "E": "JES",
    "L": "LIL",
    "M": "MRR",
    "O": "OFF",
    "P": "PRE",
    "V": "OLI",
    "H": "VIN",
}
TAMANHO_NUMERICO = {"38": "P", "40": "M", "46": "GG"}
PADRAO_SKU_REDUZIDO = re.compile(
    r"^([A-Z]{3})(\d{3})([YAGBCJELMOPVH])(PP|GG|P|M|G|U|\d{2})$"
)


def normalizar_sku_reduzido(sku: object) -> str | None:
    """Converte apenas o formato curto conhecido; o valor recebido nunca e modificado."""
    valor = str(sku or "").strip().upper()
    correspondencia = PADRAO_SKU_REDUZIDO.fullmatch(valor)
    if not correspondencia:
        return None
    categoria, modelo, cor_curta, tamanho_origem = correspondencia.groups()
    if tamanho_origem.isdigit():
        tamanho = (
            "PP"
            if int(tamanho_origem) <= 36
            else TAMANHO_NUMERICO.get(tamanho_origem, tamanho_origem)
        )
    else:
        tamanho = tamanho_origem
    if tamanho is None:
        return None
    return f"VLT-{categoria}-{modelo}-{COR_REDUZIDA[cor_curta]}-{tamanho}"


def resolver_id_variacao[T](sku: object, variacoes_por_sku: Mapping[str, T]) -> T | None:
    """Busca primeiro pelo SKU literal e depois pelo alias curto inequivoco."""
    valor = str(sku or "").strip()
    encontrado = variacoes_por_sku.get(valor)
    if encontrado is not None:
        return encontrado
    normalizado = normalizar_sku_reduzido(valor)
    return variacoes_por_sku.get(normalizado) if normalizado else None
