from decimal import Decimal

from scripts.vulto_integracao.plano_importacao import planejar_importacao


CPF_VALIDO = "52998224725"


def _referencias():
    return {
        "usuarios": [
            {
                "id_usuario": "cliente-1",
                "id_tipo_usuario": "tipo-cliente",
                "documento": CPF_VALIDO,
                "ativo": "true",
            }
        ],
        "tipos_usuario": [{"id_tipo_usuario": "tipo-cliente", "codigo": "cliente"}],
        "lojas": [{"codigo": "LOJA-VULTO-BATEL", "id_loja": "loja-4"}],
        "status_pedido": [
            {"codigo": "pago", "id_status_pedido": "status-pago"},
            {"codigo": "aguardando_pagamento", "id_status_pedido": "status-aguardando"},
            {"codigo": "cancelado", "id_status_pedido": "status-cancelado"},
        ],
        "variacoes": [{"sku": "SKU-1", "id_variacao": "variacao-1"}],
        "compras": [],
    }


def _venda(**campos):
    return {
        "id": 123,
        "loja_id": 4,
        "status_padronizado": "concluida",
        "cpf_padronizado": CPF_VALIDO,
        "data_hora_padronizada": "2025-03-02T12:00:00-03:00",
        "total_decimal": "105.00",
        "frete_decimal": "15.00",
        "desconto_decimal": "10.00",
        **campos,
    }


def _item(**campos):
    return {
        "venda_id": 123,
        "sku_padronizado": "SKU-1",
        "qtd": 1,
        "preco_unitario_decimal": "100.00",
        **campos,
    }


def _planejar(vendas=None, itens=None, **refs):
    referencia = _referencias()
    referencia.update(refs)
    return planejar_importacao(
        vendas=[_venda()] if vendas is None else vendas,
        itens=[_item()] if itens is None else itens,
        **referencia,
    )


def test_planeja_pedido_com_desconto_rateado_e_frete_separado():
    plano = _planejar(itens=[_item(preco_unitario_decimal="100,00")])

    assert plano["nao_gravou_no_banco"] is True
    assert plano["total_pedidos_planejados"] == 1
    pedido = plano["pedidos"][0]
    assert pedido["numero_pedido"] == "VULTO-123"
    assert pedido["valor_total"] == Decimal("105.00")
    assert pedido["valor_frete"] == Decimal("15.00")
    assert pedido["canal_venda"] == "loja"
    assert "status original: concluida" in pedido["observacao"]
    assert plano["itens_pedido"][0]["preco_unitario"] == Decimal("90.00")


def test_nao_planeja_venda_sem_cliente():
    plano = _planejar(usuarios=[])

    assert plano["total_pedidos_planejados"] == 0
    assert "cliente:cliente_nao_encontrado_por_cpf" in plano["pendencias"][0]["motivos"]
    assert plano["pendencias"][0]["dados_origem"]["venda"]["cpf_padronizado"] == CPF_VALIDO
    assert plano["pendencias"][0]["dados_origem"]["itens"][0]["sku_padronizado"] == "SKU-1"


def test_preserva_status_estornada_na_observacao_ao_mapear_para_cancelado():
    plano = _planejar(vendas=[_venda(status_padronizado="estornada")])

    assert plano["pedidos"][0]["id_status_pedido"] == "status-cancelado"
    assert "status original: estornada" in plano["pedidos"][0]["observacao"]


def test_cd_nao_e_loja_de_venda():
    venda = _venda(loja_id=7)
    plano = _planejar(vendas=[venda])

    assert plano["total_pedidos_planejados"] == 0
    assert "loja:sem_correspondencia_ou_nao_aplicavel" in plano["pendencias"][0]["motivos"]


def test_sku_ausente_no_catalogo_fica_pendente():
    plano = _planejar(variacoes=[])

    assert plano["total_pedidos_planejados"] == 0
    assert "sku:variacao_nao_encontrada" in plano["pendencias"][0]["motivos"]


def test_itens_mesmo_sku_e_mesmo_preco_sao_consolidados():
    venda = _venda(total_decimal="315.00", frete_decimal="15.00", desconto_decimal="0")
    itens = [
        _item(qtd=1, preco_unitario_decimal="100.00"),
        _item(qtd=2, preco_unitario_decimal="100.00"),
    ]
    plano = _planejar(vendas=[venda], itens=itens)

    assert plano["total_pedidos_planejados"] == 1
    assert len(plano["itens_pedido"]) == 1
    assert plano["itens_pedido"][0]["quantidade"] == 3
