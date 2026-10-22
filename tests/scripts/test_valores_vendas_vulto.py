from decimal import Decimal

from scripts.vulto_integracao.valores_vendas import reconciliar_valores_venda


def _item(sku, qtd, preco):
    return {
        "sku_padronizado": sku,
        "qtd": qtd,
        "preco_unitario_decimal": preco,
    }


def test_rateia_desconto_proporcional_e_separa_frete():
    resultado = reconciliar_valores_venda(
        {"total_decimal": "105.00", "frete_decimal": "15.00", "desconto_decimal": "10.00"},
        [_item("SKU-1", 1, "60.00"), _item("SKU-2", 1, "40.00")],
    )

    assert resultado["situacao"] == "desconto_rateado"
    assert [item["preco_unitario_decimal"] for item in resultado["itens"]] == [
        Decimal("54.00"),
        Decimal("36.00"),
    ]
    assert sum(item["preco_unitario_decimal"] for item in resultado["itens"]) == Decimal(
        "90.00"
    )


def test_mantem_valores_quando_nao_ha_desconto():
    resultado = reconciliar_valores_venda(
        {"total_decimal": "115.00", "frete_decimal": "15.00", "desconto_decimal": "0"},
        [_item("SKU-1", 1, "100.00")],
    )

    assert resultado["situacao"] == "sem_ajuste"
    assert resultado["itens"][0]["preco_unitario_decimal"] == "100.00"


def test_nao_forca_divergencia_sem_explicacao():
    resultado = reconciliar_valores_venda(
        {"total_decimal": "109.90", "frete_decimal": "0", "desconto_decimal": "0"},
        [_item("SKU-1", 1, "100.00")],
    )

    assert resultado["situacao"] == "pendente_divergencia_total"
    assert resultado["total_calculado"] == Decimal("100.00")


def test_devolucao_fica_pendente_sem_converter_sinal_financeiro():
    resultado = reconciliar_valores_venda(
        {"total_decimal": "0", "frete_decimal": "0", "desconto_decimal": "0"},
        [_item("SKU-1", -1, "100.00")],
    )

    assert resultado["situacao"] == "pendente_devolucao"


def test_rateio_que_nao_pode_ser_exato_no_preco_unitario_fica_pendente():
    resultado = reconciliar_valores_venda(
        {"total_decimal": "2.99", "frete_decimal": "0", "desconto_decimal": "0.01"},
        [_item("SKU-1", 2, "1.50")],
    )

    assert resultado["situacao"] == "pendente_rateio_incompativel_com_centavos"
