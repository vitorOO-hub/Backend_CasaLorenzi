"""Testes das rotas de compras sem banco real."""

from app.compras.erros import PedidoNaoEncontrado
from app.core.db import get_executar

ID_UUID = "6f1c3a52-6a4e-4c8e-9a39-0f1f2b6f2f10"
LINHA = {"id_pedido": ID_UUID, "numero_pedido": "PED-0001"}

ROTAS_COMPRAS_ESPERADAS = {
    ("GET", "/compras/pedidos"),
    ("POST", "/compras/pedidos"),
    ("GET", "/compras/pedidos/{id_pedido}"),
    ("PATCH", "/compras/pedidos/{id_pedido}"),
    ("PATCH", "/compras/pedidos/{id_pedido}/status"),
    ("POST", "/compras/pedidos/{id_pedido}/cancelar"),
    ("GET", "/compras/pedidos/{id_pedido}/itens"),
    ("POST", "/compras/pedidos/{id_pedido}/itens"),
    ("GET", "/compras/itens-pedido/{id_item_pedido}"),
    ("PATCH", "/compras/itens-pedido/{id_item_pedido}"),
    ("DELETE", "/compras/itens-pedido/{id_item_pedido}"),
    ("GET", "/compras/pedidos/{id_pedido}/pagamentos"),
    ("POST", "/compras/pedidos/{id_pedido}/pagamentos"),
    ("GET", "/compras/pagamentos/{id_pagamento}"),
    ("PATCH", "/compras/pagamentos/{id_pagamento}/status"),
}


def usar_executor(app, executor):
    app.dependency_overrides[get_executar] = lambda: executor


def devolve(resultado):
    return lambda _operacao: resultado


def levanta(erro):
    def executor(_operacao):
        raise erro

    return executor


def test_rotas_de_compras_estao_registradas(cliente):
    caminhos = cliente.get("/openapi.json").json()["paths"]
    registradas = {
        (metodo.upper(), caminho) for caminho, itens in caminhos.items() for metodo in itens
    }
    assert ROTAS_COMPRAS_ESPERADAS.issubset(registradas)


def test_criar_pedido_responde_201(app, cliente):
    usar_executor(app, devolve(LINHA))
    resposta = cliente.post(
        "/compras/pedidos",
        json={
            "numero_pedido": "PED-0001",
            "id_loja": ID_UUID,
            "id_cliente": ID_UUID,
            "id_status_pedido": ID_UUID,
            "valor_total": "0.00",
        },
    )
    assert resposta.status_code == 201
    assert resposta.json() == LINHA


def test_pedido_inexistente_responde_404(app, cliente):
    usar_executor(app, levanta(PedidoNaoEncontrado()))
    resposta = cliente.get(f"/compras/pedidos/{ID_UUID}")
    assert resposta.status_code == 404
    assert resposta.json() == {"detail": "Pedido nao encontrado"}


def test_cancelar_pedido_responde_200(app, cliente):
    usar_executor(app, devolve({"id_pedido": ID_UUID, "status": "Cancelado"}))
    resposta = cliente.post(f"/compras/pedidos/{ID_UUID}/cancelar")
    assert resposta.status_code == 200
    assert resposta.json()["status"] == "Cancelado"


def test_criar_item_rejeita_quantidade_invalida(cliente):
    resposta = cliente.post(
        f"/compras/pedidos/{ID_UUID}/itens",
        json={"id_variacao": ID_UUID, "quantidade": 0, "preco_unitario": "149.90"},
    )
    assert resposta.status_code == 422


def test_criar_pagamento_duplicado_responde_409(app, cliente, erro_integridade):
    usar_executor(app, levanta(erro_integridade("23505")))
    resposta = cliente.post(
        f"/compras/pedidos/{ID_UUID}/pagamentos",
        json={
            "tentativa": 1,
            "id_metodo_pagamento": ID_UUID,
            "id_status_pagamento": ID_UUID,
            "valor": "149.90",
        },
    )
    assert resposta.status_code == 409
    assert resposta.json() == {"detail": "Registro de compra ja existe"}


def test_atualizar_status_pagamento_responde_200(app, cliente):
    usar_executor(app, devolve({"id_pagamento": ID_UUID, "id_status_pagamento": ID_UUID}))
    resposta = cliente.patch(
        f"/compras/pagamentos/{ID_UUID}/status",
        json={"id_status_pagamento": ID_UUID},
    )
    assert resposta.status_code == 200
    assert resposta.json()["id_pagamento"] == ID_UUID
