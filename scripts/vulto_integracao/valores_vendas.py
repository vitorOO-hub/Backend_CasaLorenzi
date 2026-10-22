"""Reconcilia valores historicos sem inventar descontos, fretes ou itens."""

from collections.abc import Mapping, Sequence
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


CENTAVO = Decimal("0.01")


def _decimal(valor: object) -> Decimal | None:
    if valor is None or str(valor).strip() == "":
        return None
    try:
        return Decimal(str(valor).strip().replace(",", ".")).quantize(CENTAVO)
    except Exception:
        return None


def _ratear_desconto(
    itens: Sequence[Mapping[str, Any]], desconto: Decimal
) -> list[dict[str, Any]] | None:
    """Rateia desconto por valor bruto; retorna None se preco unitario nao fechar centavos."""
    valores = []
    for item in itens:
        quantidade = int(Decimal(str(item["qtd"])))
        preco = _decimal(item.get("preco_unitario_decimal"))
        if quantidade <= 0 or preco is None or preco < 0:
            return None
        bruto_centavos = int((preco * quantidade * 100).to_integral_value())
        valores.append((item, quantidade, int(preco * 100), bruto_centavos))

    bruto_total = sum(bruto for _, _, _, bruto in valores)
    desconto_centavos = int(desconto * 100)
    if desconto_centavos < 0 or desconto_centavos > bruto_total or bruto_total == 0:
        return None

    partes = []
    for item, quantidade, preco_centavos, bruto in valores:
        exato = Decimal(desconto_centavos * bruto) / Decimal(bruto_total)
        base = int(exato)
        partes.append(
            {
                "item": item,
                "quantidade": quantidade,
                "preco_centavos": preco_centavos,
                "bruto_centavos": bruto,
                "desconto_centavos": base,
                "resto": exato - base,
            }
        )

    faltam = desconto_centavos - sum(parte["desconto_centavos"] for parte in partes)
    ordem = sorted(range(len(partes)), key=lambda i: partes[i]["resto"], reverse=True)
    for indice in ordem[:faltam]:
        partes[indice]["desconto_centavos"] += 1

    # A tabela de itens guarda preco por unidade: cada desconto da linha precisa
    # ser divisivel pela quantidade para preservar exatamente o total em centavos.
    resultado = []
    for parte in partes:
        quantidade = parte["quantidade"]
        desconto_linha = parte["desconto_centavos"]
        if desconto_linha % quantidade:
            return None
        desconto_unitario = desconto_linha // quantidade
        novo_preco = parte["preco_centavos"] - desconto_unitario
        if novo_preco < 0:
            return None
        resultado.append(
            {
                **parte["item"],
                "preco_unitario_decimal": (Decimal(novo_preco) / 100).quantize(CENTAVO),
            }
        )
    return resultado


def reconciliar_valores_venda(
    venda: Mapping[str, Any], itens: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Classifica uma venda; so ajusta preco quando a equacao fecha sem ambiguidade."""
    total = _decimal(venda.get("total_decimal"))
    frete = _decimal(venda.get("frete_decimal")) or Decimal("0.00")
    desconto = _decimal(venda.get("desconto_decimal")) or Decimal("0.00")
    if total is None or not itens:
        return {"situacao": "pendente_valor_ausente", "itens": list(itens)}

    bruto = Decimal("0.00")
    for item in itens:
        qtd = _decimal(item.get("qtd"))
        preco = _decimal(item.get("preco_unitario_decimal"))
        if qtd is None or qtd != qtd.to_integral_value() or preco is None or preco < 0:
            return {"situacao": "pendente_item_invalido", "itens": list(itens)}
        bruto += qtd * preco
    bruto = bruto.quantize(CENTAVO)

    if any((_decimal(item.get("qtd")) or 0) <= 0 for item in itens):
        return {"situacao": "pendente_devolucao", "itens": list(itens)}
    if total == bruto + frete and desconto == 0:
        return {"situacao": "sem_ajuste", "itens": list(itens)}
    if total == bruto + frete - desconto and desconto > 0:
        itens_ajustados = _ratear_desconto(itens, desconto)
        if itens_ajustados is None:
            return {"situacao": "pendente_rateio_incompativel_com_centavos", "itens": list(itens)}
        return {"situacao": "desconto_rateado", "itens": itens_ajustados}
    return {
        "situacao": "pendente_divergencia_total",
        "itens": list(itens),
        "total_planilha": total,
        "total_calculado": (bruto + frete - desconto).quantize(CENTAVO),
    }
