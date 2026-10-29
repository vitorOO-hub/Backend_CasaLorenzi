"""Regras do item comprado usado no agendamento de ajuste."""

from datetime import date
from uuid import uuid4

import pytest

from app.cliente import repositorio
from app.cliente.erros import AjustePedidoNaoEntregue, PedidoClienteNaoEncontrado


class Resultado:
    def __init__(self, linha):
        self.linha = linha

    def mappings(self):
        return self

    def first(self):
        return self.linha


class Conexao:
    def __init__(self, linha):
        self.linha = linha
        self.parametros = None
        self.consulta = None

    def execute(self, consulta, parametros):
        self.consulta = str(consulta)
        self.parametros = parametros
        return Resultado(self.linha)


def test_item_entregue_pertence_ao_cliente_e_fornece_dados_da_peca():
    cliente, item_id, pedido_id = uuid4(), uuid4(), uuid4()
    linha = {
        "id_item_pedido": item_id,
        "id_pedido": pedido_id,
        "status": "entregue",
        "sku": "CL-CAL-M",
        "peca_nome": "Calça Lorenzi",
    }
    conexao = Conexao(linha)

    assert repositorio._item_comprado_para_ajuste(conexao, cliente, item_id) == linha
    assert conexao.parametros == {"item": str(item_id), "cliente": str(cliente)}
    assert "p.id_cliente = CAST(:cliente AS uuid)" in conexao.consulta


def test_item_inexistente_ou_de_outra_cliente_nao_pode_ser_agendado():
    with pytest.raises(PedidoClienteNaoEncontrado):
        repositorio._item_comprado_para_ajuste(Conexao(None), uuid4(), uuid4())


@pytest.mark.parametrize("status", ["criado", "pago", "separado", "cancelado"])
def test_ajuste_exige_pedido_entregue(status):
    with pytest.raises(AjustePedidoNaoEntregue):
        repositorio._item_comprado_para_ajuste(Conexao({"status": status}), uuid4(), uuid4())


def test_agendamento_vincula_pedido_e_item_e_ignora_nome_enviado_pelo_cliente(monkeypatch):
    cliente, item_id, pedido_id, atendimento_id, loja = (uuid4() for _ in range(5))
    item = {
        "id_item_pedido": item_id,
        "id_pedido": pedido_id,
        "sku": "SKU-REAL",
        "peca_nome": "Peça comprada",
    }
    monkeypatch.setattr(repositorio, "_item_comprado_para_ajuste", lambda *args: item)
    monkeypatch.setattr(repositorio, "_obter_id_opcao_atendimento", lambda *args: uuid4())
    monkeypatch.setattr(
        repositorio,
        "obter_chamado_cliente",
        lambda conexao, id_cliente, id_atendimento: {"id_atendimento": id_atendimento},
    )

    class ResultadoGravacao:
        def __init__(self, linha=None):
            self.linha = linha

        def mappings(self):
            return self

        def first(self):
            return self.linha

        def scalar_one(self):
            return atendimento_id

    class ConexaoGravacao:
        def __init__(self):
            self.comandos = []
            self.confirmado = False

        def execute(self, consulta, parametros):
            sql = str(consulta)
            self.comandos.append((sql, parametros))
            if "FROM agenda_horario ah" in sql:
                return ResultadoGravacao({"usados": 0, "capacidade": 2})
            return ResultadoGravacao()

        def commit(self):
            self.confirmado = True

        def rollback(self):
            pytest.fail("Um agendamento válido não deve reverter a transação")

    conexao = ConexaoGravacao()
    resultado = repositorio.criar_agendamento_cliente(
        conexao,
        cliente,
        {
            "tipo": "ajuste",
            "id_item_pedido": item_id,
            "id_loja": loja,
            "data": date(2026, 10, 30),
            "horario": "14:00",
            "nome": "Cliente",
            "telefone": "11999990000",
            "peca_sku": "SKU-FALSO",
            "peca_nome": "Outra peça",
            "observacao": "Fazer a barra",
        },
    )

    assert conexao.confirmado
    assert resultado == {"id_atendimento": atendimento_id}
    atendimento = next(p for sql, p in conexao.comandos if "INSERT INTO atendimento (" in sql)
    vinculo = next(p for sql, p in conexao.comandos if "INSERT INTO atendimento_item" in sql)
    agendamento = next(p for sql, p in conexao.comandos if "INSERT INTO agendamento_cliente" in sql)
    assert atendimento["pedido"] == str(pedido_id)
    assert vinculo == {"atendimento": str(atendimento_id), "item": str(item_id)}
    assert agendamento["peca_sku"] == "SKU-REAL"
    assert agendamento["peca_nome"] == "Peça comprada"
