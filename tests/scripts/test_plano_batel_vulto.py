from decimal import Decimal

from scripts.vulto_integracao.plano_batel import planejar_vendas_batel


def _refs():
    return {
        "lojas": [{"codigo": "LOJA-VULTO-BATEL", "id_loja": "loja-batel"}],
        "status_pedido": [
            {"codigo": "pago", "id_status_pedido": "status-pago"},
            {"codigo": "cancelado", "id_status_pedido": "status-cancelado"},
        ],
        "variacoes": [{"sku": "VLT-CAL-001-PRE-M", "id_variacao": "variacao-calca"}],
        "usuarios": [
            {
                "id_usuario": "cliente-1",
                "id_tipo_usuario": "tipo-cliente",
                "documento": "52998224725",
                "ativo": "true",
            }
        ],
        "tipos_usuario": [{"id_tipo_usuario": "tipo-cliente", "codigo": "cliente"}],
    }


def _venda(**campos):
    return {
        "data_hora": "2026-03-02T15:46:00-03:00",
        "cpf": "529.982.247-25",
        "valor": 269.90,
        "status": "concluida",
        "revisao_duplicidade": "sem duplicidade confirmada no vulto.db",
        "chave_origem_importacao": "vendas_batel_manual_marco:linha_2",
        "funcionario_legado_id": 15,
        "vendedora_padrao": "vendedora batel",
        **campos,
    }


def _item(**campos):
    return {
        "linha_venda": 2,
        "sku_confirmado": "VLT-CAL-001-PRE-M",
        "quantidade_item": 1,
        "status_mapeamento": "mapeado",
        **campos,
    }


def _planejar(vendas=None, itens=None, **refs):
    dados = _refs()
    dados.update(refs)
    return planejar_vendas_batel(
        vendas=[_venda()] if vendas is None else vendas,
        itens_mapeados=[_item()] if itens is None else itens,
        codigo_lote="LOTE-TESTE",
        **dados,
    )


def test_importa_venda_batel_com_cliente_e_preco_do_item_ausente():
    plano = _planejar()

    assert plano["total_pedidos_planejados"] == 1
    assert plano["pedidos"][0]["id_cliente"] == "cliente-1"
    assert plano["pedidos"][0]["valor_total"] == Decimal("269.90")
    assert plano["itens_pedido"][0]["preco_unitario"] is None
    assert plano["rastreabilidade"][0]["chave_origem"] == "vendas_batel_manual_marco:linha_2"


def test_importa_sem_cpf_sem_criar_cliente_falso():
    plano = _planejar(vendas=[_venda(cpf=None)])

    assert plano["pedidos"][0]["id_cliente"] is None


def test_preserva_estorno_negativo_e_mapeia_status_cancelado():
    plano = _planejar(vendas=[_venda(status="estornada", valor=-359.90)])

    assert plano["pedidos"][0]["id_status_pedido"] == "status-cancelado"
    assert plano["pedidos"][0]["valor_total"] == Decimal("-359.90")
    assert plano["rastreabilidade"][0]["dados_origem"]["venda"]["status"] == "estornada"


def test_deixa_venda_pendente_quando_sku_nao_existe_no_destino():
    plano = _planejar(variacoes=[])

    assert plano["total_pedidos_planejados"] == 0
    assert "sku:variacao_nao_encontrada:VLT-CAL-001-PRE-M" in plano["pendencias"][0]["motivos"]


def test_nao_importa_venda_sem_confirmacao_explicita_de_nao_duplicidade():
    plano = _planejar(vendas=[_venda(revisao_duplicidade="nao aplicavel")])

    assert plano["total_pedidos_planejados"] == 0
    assert plano["pendencias"][0]["motivos"] == [
        "duplicidade:sem_confirmacao_para_importar"
    ]
