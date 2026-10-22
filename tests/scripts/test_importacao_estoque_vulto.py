from decimal import Decimal

import pytest

from scripts.vulto_integracao.estoque import (
    ImportacaoEstoqueError,
    completar_snapshot_com_saldos_zero,
    preparar_catalogo,
    preparar_movimentos,
    preparar_snapshot,
)

LOJAS = {
    "LOJA-VULTO-PINHEIROS": "loja-1",
    "LOJA-VULTO-SHOPPING-ELDORADO": "loja-2",
    "LOJA-VULTO-SAVASSI": "loja-3",
    "LOJA-VULTO-BATEL": "loja-4",
    "LOJA-VULTO-E-COMMERCE": "loja-5",
    "LOJA-VULTO-APP": "loja-6",
    "LOJA-CD-CAJAMAR": "loja-7",
}


def test_snapshot_preserva_quantidade_negativa():
    snapshot = preparar_snapshot(
        [
            {
                "loja_id": 4,
                "sku_padronizado": "SKU-DEVOLUCAO",
                "qtd": -3,
                "data_padronizada": "2026-03-22T10:00:00-03:00",
            }
        ],
        LOJAS,
    )

    assert snapshot[0]["quantidade"] == -3


def test_movimentos_reconstroem_historico_com_saldo_negativo():
    snapshot = preparar_snapshot(
        [
            {
                "loja_id": 4,
                "sku_padronizado": "SKU-DEVOLUCAO",
                "qtd": -1,
                "data_padronizada": "2026-03-22T10:00:00-03:00",
            }
        ],
        LOJAS,
    )
    movimentos = preparar_movimentos(
        [
            {
                "id": 1,
                "loja_id": 4,
                "sku_padronizado": "SKU-DEVOLUCAO",
                "qtd": 2,
                "tipo_movimento": "saida_transferencia",
                "loja_destino": 3,
                "data_padronizada": "2026-03-20T10:00:00-03:00",
            }
        ],
        snapshot,
        LOJAS,
    )

    assert movimentos[0]["quantidade_anterior"] == 1
    assert movimentos[0]["quantidade_posterior"] == -1
    assert movimentos[0]["id_loja_destino"] == "loja-3"


def test_movimento_reconstruido_sem_id_usa_referencia_do_envio():
    snapshot = preparar_snapshot(
        [
            {
                "loja_id": 2,
                "sku_padronizado": "SKU-RECONSTRUIDO",
                "qtd": 1,
                "data_padronizada": "2026-03-22T10:00:00-03:00",
            }
        ],
        LOJAS,
    )
    movimento = preparar_movimentos(
        [
            {
                "id": None,
                "loja_id": 2,
                "sku_padronizado": "SKU-RECONSTRUIDO",
                "qtd": 1,
                "tipo_movimento": "entrada",
                "obs": "entrada nao registrada; deduzida do envio id 12345",
                "data_padronizada": "2026-03-20T10:00:00-03:00",
            }
        ],
        snapshot,
        LOJAS,
    )[0]

    assert movimento["id_origem"] == "derivado-envio-12345"
    assert movimento["dados_origem"]["id"] is None


def test_entrada_transferida_mantem_loja_destino_e_registra_origem_no_legado():
    snapshot = preparar_snapshot(
        [
            {
                "loja_id": 3,
                "sku_padronizado": "SKU-TRANSFERENCIA",
                "qtd": 2,
                "data_padronizada": "2026-03-22T10:00:00-03:00",
            }
        ],
        LOJAS,
    )
    movimento = preparar_movimentos(
        [
            {
                "id": 7,
                "loja_id": 3,
                "sku_padronizado": "SKU-TRANSFERENCIA",
                "qtd": 2,
                "tipo_movimento": "entrada",
                "obs": "veio da pinheiros",
                "data_padronizada": "2026-03-20T10:00:00-03:00",
            }
        ],
        snapshot,
        LOJAS,
    )[0]

    assert movimento["codigo_tipo"] == "transferencia_entrada"
    assert movimento["id_loja"] == "loja-3"
    assert movimento["id_loja_destino"] is None


def test_movimento_sem_saldo_final_oficial_bloqueia_importacao():
    with pytest.raises(ImportacaoEstoqueError, match="sem saldo final"):
        preparar_movimentos(
            [
                {
                    "id": 1,
                    "loja_id": 4,
                    "sku_padronizado": "SKU-SEM-SNAPSHOT",
                    "qtd": 1,
                    "tipo_movimento": "entrada",
                    "data_padronizada": "2026-03-20T10:00:00-03:00",
                }
            ],
            [],
            LOJAS,
        )


def test_snapshot_ausente_pode_ser_completado_com_zero_aprovado():
    movimentos_origem = [
        {
            "id": 12,
            "loja_id": 7,
            "sku_padronizado": "SKU-CD-ZERADO",
            "qtd": 3,
            "tipo_movimento": "saida_transferencia",
            "loja_destino": 4,
            "data_padronizada": "2026-03-20T10:00:00-03:00",
        }
    ]
    snapshot = completar_snapshot_com_saldos_zero([], movimentos_origem, LOJAS)
    movimento = preparar_movimentos(movimentos_origem, snapshot, LOJAS)[0]

    assert snapshot[0]["quantidade"] == 0
    assert snapshot[0]["saldo_inferido_por_ausencia"] is True
    assert movimento["quantidade_anterior"] == 3
    assert movimento["quantidade_posterior"] == 0
    assert movimento["snapshot_ausente_tratado_como_zero"] is True


def test_produtos_diferentes_com_codigos_parecidos_separam_pais():
    produtos, variacoes = preparar_catalogo(
        [
            {
                "sku": "VLT-MOL-002-OLI-G",
                "produto": "hoodie oversized basico oli",
                "categoria": "moletom",
                "cor": "oli",
                "tamanho": "G",
                "preco": "399,90",
                "acao_importacao": "cadastrar",
            },
            {
                "sku": "VLT-TRI-001-AMA-G",
                "produto": "colete trico trancado",
                "categoria": "tricô",
                "cor": "ama",
                "tamanho": "G",
                "preco": Decimal("299.90"),
                "acao_importacao": "cadastrar",
            },
        ],
        [],
        {"VLT-MOL-002-OLI-G", "VLT-TRI-001-AMA-G"},
        set(),
    )

    assert len(produtos) == 2
    assert len({variacao["produto_chave"] for variacao in variacoes}) == 2
    assert produtos[0]["preco_base"] == Decimal("399.90")


def test_sku_provisorio_planeja_produto_inativo():
    produtos, variacoes = preparar_catalogo(
        [],
        [{"sku_provisorio": "TMP-VULTO-001"}],
        {"TMP-VULTO-001"},
        set(),
    )

    assert produtos[0]["ativo"] is False
    assert variacoes[0]["ativa"] is False
