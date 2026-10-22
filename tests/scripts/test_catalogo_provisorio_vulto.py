from scripts.vulto_integracao.catalogo_provisorio import planejar_placeholders_catalogo


def test_planeja_um_placeholder_inativo_por_sku_ausente():
    plano = planejar_placeholders_catalogo(
        ["SKU-A", "SKU-B", "SKU-A", None, ""],
        [
            {"sku": "SKU-A", "ativa": "false"},
            {"sku": "SKU-EXTRA", "ativa": "true"},
        ],
    )

    assert len(plano) == 1
    assert plano[0]["sku"] == "SKU-B"
    assert plano[0]["produto_ativo"] is False
    assert plano[0]["variacao_ativa"] is False
    assert plano[0]["preco_base"] == 0
    assert plano[0]["preco_venda"] == 0
    assert plano[0]["cor"] and plano[0]["tamanho"]


def test_sku_existente_inativo_nao_recebe_placeholder():
    plano = planejar_placeholders_catalogo(
        ["SKU-HISTORICO"], [{"sku": "SKU-HISTORICO", "ativa": "false"}]
    )

    assert plano == []
