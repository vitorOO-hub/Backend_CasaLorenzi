from scripts.vulto_integracao.skus import normalizar_sku_reduzido, resolver_id_variacao


def test_converte_sku_curto_sem_alterar_codigo_original():
    assert normalizar_sku_reduzido("ACE011BU") == "VLT-ACE-011-BRA-U"
    assert normalizar_sku_reduzido("CAL022GPP") == "VLT-CAL-022-BEG-PP"


def test_mantem_sku_canonico_fora_da_conversao():
    assert normalizar_sku_reduzido("VLT-CAL-001-OLI-M") is None


def test_resolve_alias_curto_apenas_para_variacao_existente():
    variacoes = {"VLT-ACE-011-BRA-U": "var-1"}

    assert resolver_id_variacao("ACE011BU", variacoes) == "var-1"
    assert resolver_id_variacao("ACE011BP", variacoes) is None


def test_tamanhos_42_e_44_resolvem_para_a_mesma_variacao_g():
    variacoes = {"VLT-CAL-001-OLI-G": "var-g"}

    assert normalizar_sku_reduzido("CAL001V42") == "VLT-CAL-001-OLI-G"
    assert normalizar_sku_reduzido("CAL001V44") == "VLT-CAL-001-OLI-G"
    assert resolver_id_variacao("CAL001V42", variacoes) == "var-g"
    assert resolver_id_variacao("CAL001V44", variacoes) == "var-g"
