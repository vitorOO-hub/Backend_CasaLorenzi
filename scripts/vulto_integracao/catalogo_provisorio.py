"""Planeja produtos inativos para SKUs do legado sem variacao correspondente."""

from collections.abc import Iterable, Mapping
from decimal import Decimal

MARCA_VULTO = "Vulto"
CATEGORIA_PENDENTE = "pendente_identificacao"
COLECAO_MIGRACAO = "migracao vulto"


def planejar_placeholders_catalogo(
    skus_origem: Iterable[object], variacoes_existentes: Iterable[Mapping[str, object]]
) -> list[dict[str, object]]:
    """Cria especificacoes inativas, sem persistir nem substituir variacoes existentes."""
    skus_existentes = {
        str(linha.get("sku") or "").strip()
        for linha in variacoes_existentes
        if str(linha.get("sku") or "").strip()
    }
    skus_origem_unicos = {
        str(sku).strip() for sku in skus_origem if sku is not None and str(sku).strip()
    }

    return [
        {
            "sku": sku,
            "nome_produto": f"legado pendente de identificacao - {sku}",
            "marca": MARCA_VULTO,
            "categoria": CATEGORIA_PENDENTE,
            "colecao": COLECAO_MIGRACAO,
            "preco_base": Decimal("0.00"),
            "produto_ativo": False,
            "cor": "nao_identificado",
            "tamanho": "U",
            "preco_venda": Decimal("0.00"),
            "variacao_ativa": False,
        }
        for sku in sorted(skus_origem_unicos - skus_existentes)
    ]
