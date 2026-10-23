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


def test_snapshot_zera_saldo_negativo_e_preserva_quantidade_de_origem():
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

    assert snapshot[0]["quantidade"] == 0
    assert snapshot[0]["quantidade_origem"] == -3
    assert snapshot[0]["saldo_negativo_zerado"] is True


def test_movimentos_preservam_historico_e_registram_ajuste_de_migracao():
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

    movimento_legado, ajuste_migracao = movimentos
    assert movimento_legado["quantidade_anterior"] == 1
    assert movimento_legado["quantidade_posterior"] == -1
    assert movimento_legado["id_loja_destino"] == "loja-3"
    assert ajuste_migracao["codigo_tipo"] == "ajuste_positivo"
    assert ajuste_migracao["quantidade"] == 1
    assert ajuste_migracao["quantidade_anterior"] == -1
    assert ajuste_migracao["quantidade_posterior"] == 0
    assert ajuste_migracao["dados_origem"]["movimento_sintetico"] is True
    assert "nao representa entrada fisica" in ajuste_migracao["motivo"]


def test_saldo_positivo_nao_gera_ajuste_de_zeramento():
    snapshot = preparar_snapshot(
        [
            {
                "loja_id": 4,
                "sku_padronizado": "SKU-POSITIVO",
                "qtd": 4,
                "data_padronizada": "2026-03-22T10:00:00-03:00",
            }
        ],
        LOJAS,
    )
    movimentos = preparar_movimentos([], snapshot, LOJAS)

    assert snapshot[0]["quantidade"] == 4
    assert movimentos == []


def test_saldo_negativo_sem_movimentos_gera_ajuste_para_zero():
    snapshot = preparar_snapshot(
        [
            {
                "loja_id": 4,
                "sku_padronizado": "SKU-NEGATIVO-SEM-MOVIMENTO",
                "qtd": -2,
                "data_padronizada": "2026-03-22T10:00:00-03:00",
            }
        ],
        LOJAS,
    )
    ajuste = preparar_movimentos([], snapshot, LOJAS)[0]

    assert ajuste["codigo_tipo"] == "ajuste_positivo"
    assert ajuste["quantidade"] == 2
    assert ajuste["quantidade_anterior"] == -2
    assert ajuste["quantidade_posterior"] == 0


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
