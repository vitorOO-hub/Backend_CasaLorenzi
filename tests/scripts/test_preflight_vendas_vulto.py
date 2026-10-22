from scripts.vulto_integracao import preflight_vendas as modulo_preflight


class AbaFalsa:
    def __init__(self, linhas):
        self.linhas = linhas

    def iter_rows(self, values_only=False):
        if not self.linhas:
            yield ()
            return
        cabecalhos = list(self.linhas[0])
        yield tuple(cabecalhos)
        for linha in self.linhas:
            yield tuple(linha.get(cabecalho) for cabecalho in cabecalhos)


class PlanilhaFalsa:
    def __init__(self, abas):
        self.abas = abas
        self.sheetnames = list(abas)

    def __getitem__(self, nome):
        return AbaFalsa(self.abas[nome])


def _preflight(monkeypatch, vendas, itens, compras):
    abas = {
        "vendas_importacao": vendas,
        "itens_venda_importacao": itens,
        "compras_importacao": compras,
    }
    monkeypatch.setattr(
        modulo_preflight, "load_workbook", lambda *args, **kwargs: PlanilhaFalsa(abas)
    )
    return modulo_preflight.preflight_vendas("vulto.xlsx")


def test_preflight_classifica_sem_escrever_e_mantem_vinculo_pendente(monkeypatch):
    relatorio = _preflight(
        monkeypatch,
        [
            {
                "id": 1,
                "loja_id": 4,
                "status_padronizado": "concluida",
                "cpf_padronizado": None,
                "compra_id_resolvida": 9,
                "situacao_vinculo_compra": "vinculado_confirmado",
                "canal": "PDV",
                "canal_padronizado": "vulto batel",
            },
            {
                "id": 2,
                "loja_id": 4,
                "status_padronizado": "estornada",
                "cpf_padronizado": None,
                "compra_id_resolvida": 10,
                "situacao_vinculo_compra": "pendente_sem_compra_em_30s",
                "canal": "PDV",
                "canal_padronizado": "vulto batel",
            },
        ],
        [
            {
                "venda_id": 1,
                "sku_padronizado": "SKU-1",
                "qtd": 1,
                "preco_unitario_decimal": 99.9,
                "pendencias": None,
            },
            {
                "venda_id": 2,
                "sku_padronizado": "TMP-VULTO-2",
                "qtd": -1,
                "preco_unitario_decimal": 99.9,
                "pendencias": "sku_provisorio_nao_identificado",
            },
        ],
        [
            {"id": 9, "cpf_cliente_quando_identificavel": "52998224725"},
            {"id": 10, "cpf_cliente_quando_identificavel": "52998224725"},
        ],
    )

    assert relatorio["nao_gravou_no_banco"] is True
    assert relatorio["resolucao_cliente"]["cpf_de_compra_com_vinculo_confirmado"] == 1
    assert relatorio["resolucao_cliente"]["vinculo_compra_pendente"] == 1
    assert relatorio["itens_com_quantidade_zero"] == 0
    assert relatorio["itens_identificados_como_devolucao"] == 1
    assert relatorio["unidades_identificadas_como_devolucao"] == 1
    assert relatorio["tratamento_devolucoes"]["importacao"].startswith(
        "venda fica pendente"
    )
    assert relatorio["itens_com_sku_provisorio"] == 1
    assert relatorio["status_pedido_automatico"]["concluida"] == "pago"
    assert relatorio["status_pedido_automatico"]["estornada"] == "cancelado"
    assert relatorio["status_pendente_decisao"] == []


def test_preflight_detecta_venda_sem_item_e_loja_sem_mapeamento(monkeypatch):
    relatorio = _preflight(
        monkeypatch,
        [
            {
                "id": 1,
                "loja_id": 8,
                "status_padronizado": "aguardando",
                "cpf_padronizado": "52998224725",
                "canal": "loja",
                "canal_padronizado": "loja desconhecida",
            }
        ],
        [],
        [],
    )

    assert relatorio["vendas_sem_itens"] == 1
    assert relatorio["lojas_legado_sem_mapeamento"] == {"8": 1}
