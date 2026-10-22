from scripts.vulto_integracao.conferencia_estoque import planejar_conferencia
from scripts.vulto_integracao.skus import normalizar_sku_reduzido


def test_agrupa_sku_curto_e_compara_sem_alterar_estoque():
    relatorio = planejar_conferencia(
        estoque=[
            {"loja_id": 2, "sku": "CAL001V36", "sku_padronizado": "VLT-CAL-001-OLI-PP", "qtd": 2},
            {
                "loja_id": 2,
                "sku": "VLT-CAL-001-OLI-PP",
                "sku_padronizado": "VLT-CAL-001-OLI-PP",
                "qtd": 1,
            },
        ],
        contagens_por_aba={"Eldorado": [{"codigo": "CAL001V36", "qtde": 2}]},
    )

    assert relatorio["nao_gravou_no_banco"] is True
    assert relatorio["comparacoes"] == [
        {
            "aba_contagem": "Eldorado",
            "loja_id_vulto": 2,
            "codigo_loja": "LOJA-VULTO-SHOPPING-ELDORADO",
            "granularidade": "sku",
            "metrica_contagem": "quantidade",
            "sku_ou_modelo": "VLT-CAL-001-OLI-PP",
            "saldo_estoque_vulto": 3,
            "quantidade_contada": 2,
            "diferenca_contagem_menos_estoque": -1,
            "situacao": "divergente",
        }
    ]


def test_normaliza_tamanho_numerico_no_sku_canonico_da_contagem():
    relatorio = planejar_conferencia(
        estoque=[{"loja_id": 1, "sku_padronizado": "VLT-CAL-001-OLI-P", "qtd": 4}],
        contagens_por_aba={"PINHEIROS 20-09": [{"SKU": "VLT-CAL-001-OLI-38", "QTD": 4}]},
    )

    assert relatorio["comparacoes"][0]["situacao"] == "confere"
    assert relatorio["comparacoes"][0]["sku_ou_modelo"] == "VLT-CAL-001-OLI-P"


def test_preserva_42_e_44_como_skus_distintos_no_importador_e_na_conferencia():
    sku_42 = "VLT-CAL-001-OLI-42"
    sku_44 = "VLT-CAL-001-OLI-44"
    assert normalizar_sku_reduzido("CAL001V42") == sku_42
    assert normalizar_sku_reduzido("CAL001V44") == sku_44

    relatorio = planejar_conferencia(
        estoque=[
            {"loja_id": 1, "sku_padronizado": sku_42, "qtd": 3},
            {"loja_id": 1, "sku_padronizado": sku_44, "qtd": 5},
        ],
        contagens_por_aba={
            "Pinheiros": [{"SKU": sku_42, "QTD": 3}, {"SKU": sku_44, "QTD": 5}]
        },
    )

    assert [linha["sku_ou_modelo"] for linha in relatorio["comparacoes"]] == [sku_42, sku_44]
    assert all(linha["situacao"] == "confere" for linha in relatorio["comparacoes"])


def test_savassi_compara_por_modelo_e_preserva_ausencia_como_desconhecida():
    relatorio = planejar_conferencia(
        estoque=[
            {"loja_id": 3, "sku_padronizado": "VLT-CAL-001-OLI-P", "qtd": 2},
            {"loja_id": 3, "sku_padronizado": "VLT-CAL-001-VIN-G", "qtd": 3},
        ],
        contagens_por_aba={
            "SAVASSI (por modelo)": [
                {"modelo": "CAL-001", "descricao": "calca", "qtd_total": 6}
            ]
        },
    )

    assert relatorio["comparacoes"][0]["granularidade"] == "modelo"
    assert relatorio["comparacoes"][0]["sku_ou_modelo"] == "CAL-001"
    assert relatorio["comparacoes"][0]["diferenca_contagem_menos_estoque"] == 1
    assert relatorio["comparacoes"][0]["situacao"] == "divergente"


def test_cd_exibe_saldo_e_disponivel_separadamente():
    relatorio = planejar_conferencia(
        estoque=[{"loja_id": 7, "sku_padronizado": "VLT-CAL-001-OLI-M", "qtd": 5}],
        contagens_por_aba={
            "CD - posicao WMS": [
                {"SKU": "VLT-CAL-001-OLI-M", "SALDO": 6, "RESERVADO": 2, "DISPONIVEL": 4}
            ]
        },
    )

    assert {linha["metrica_contagem"] for linha in relatorio["comparacoes"]} == {
        "saldo",
        "disponivel",
    }
    diferencas = {linha["metrica_contagem"]: linha["diferenca_contagem_menos_estoque"]
                  for linha in relatorio["comparacoes"]}
    assert diferencas == {"saldo": 1, "disponivel": -1}


def test_item_sem_linha_de_contagem_nao_e_tratado_como_zero():
    relatorio = planejar_conferencia(
        estoque=[{"loja_id": 1, "sku_padronizado": "VLT-CAL-001-OLI-M", "qtd": 4}],
        contagens_por_aba={"Pinheiros": [{"SKU": "VLT-BER-001-PRE-M", "QTD": 2}]},
    )

    situacao = {linha["sku_ou_modelo"]: linha for linha in relatorio["comparacoes"]}
    assert situacao["VLT-CAL-001-OLI-M"]["situacao"] == "sem_registro_na_contagem"
    assert situacao["VLT-CAL-001-OLI-M"]["diferenca_contagem_menos_estoque"] is None
    assert situacao["VLT-BER-001-PRE-M"]["situacao"] == "sem_registro_no_estoque_vulto"
