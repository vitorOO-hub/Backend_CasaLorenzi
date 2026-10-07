"""Rotas da area do cliente sem banco real."""

from types import SimpleNamespace
from uuid import UUID

from app.core.db import get_executar
from app.core.papeis import Papel
from app.core.security import get_current_user

ID_AUTH = UUID("1f1c3a52-6a4e-4c8e-9a39-0f1f2b6f2f10")
ID_LOJA = "2f1c3a52-6a4e-4c8e-9a39-0f1f2b6f2f10"
ID_PEDIDO = "3f1c3a52-6a4e-4c8e-9a39-0f1f2b6f2f10"
ID_VARIACAO = "4f1c3a52-6a4e-4c8e-9a39-0f1f2b6f2f10"
ID_ITEM = "5f1c3a52-6a4e-4c8e-9a39-0f1f2b6f2f10"
ID_PAGAMENTO = "6f1c3a52-6a4e-4c8e-9a39-0f1f2b6f2f10"
ID_CHAMADO = "7f1c3a52-6a4e-4c8e-9a39-0f1f2b6f2f10"
ID_MENSAGEM = "8f1c3a52-6a4e-4c8e-9a39-0f1f2b6f2f10"
ID_CARRINHO = "af1c3a52-6a4e-4c8e-9a39-0f1f2b6f2f10"

PEDIDO = {
    "id_pedido": ID_PEDIDO,
    "numero_pedido": "PD-20261007-ABCD1234",
    "id_loja": ID_LOJA,
    "loja": "Casa Lorenzi Centro",
    "status_codigo": "pago",
    "status": "Pago",
    "valor_total": "198.90",
    "criado_em": "2026-10-07T12:00:00+00:00",
    "itens": [
        {
            "id_item_pedido": ID_ITEM,
            "id_variacao": ID_VARIACAO,
            "sku": "CL-CAM-LIN-BR-P",
            "produto": "Camisa Linho Essencial",
            "cor": "Branco",
            "tamanho": "P",
            "quantidade": 1,
            "preco_unitario": "149.90",
            "valor_total": "149.90",
        }
    ],
    "pagamento": {
        "id_pagamento": ID_PAGAMENTO,
        "metodo_codigo": "pix",
        "metodo": "PIX",
        "status_codigo": "aprovado",
        "status": "Aprovado",
        "valor": "198.90",
        "processado_em": "2026-10-07T12:00:00+00:00",
    },
}

CHAMADO = {
    "id_atendimento": ID_CHAMADO,
    "protocolo": "AT-2026-0001",
    "assunto": "Troca de tamanho",
    "categoria": {"codigo": "troca_devolucao", "nome": "Troca e devolucao"},
    "status": {"codigo": "aberto", "nome": "Aberto"},
    "id_pedido": ID_PEDIDO,
    "numero_pedido": "PD-20261007-ABCD1234",
    "id_loja": ID_LOJA,
    "loja_nome": "Casa Lorenzi Centro",
    "aberto_em": "2026-10-07T12:10:00+00:00",
    "atualizado_em": "2026-10-07T12:10:00+00:00",
    "ultima_mensagem_em": "2026-10-07T12:10:00+00:00",
    "pecas": [
        {
            "id_item_pedido": ID_ITEM,
            "id_variacao": ID_VARIACAO,
            "sku": "CL-CAM-LIN-BR-P",
            "produto": "Camisa Linho Essencial",
            "cor": "Branco",
            "tamanho": "P",
            "quantidade": 1,
        }
    ],
    "anexos": [],
}

MENSAGEM = {
    "id_mensagem": ID_MENSAGEM,
    "autor": "cliente",
    "nome": "Cliente",
    "texto": "Preciso trocar o tamanho.",
    "enviada_em": "2026-10-07T12:10:00+00:00",
}

PERFIL = {
    "id_cliente": "9f1c3a52-6a4e-4c8e-9a39-0f1f2b6f2f10",
    "nome": "Cliente",
    "email": "cliente@casalorenzi.test",
    "telefone": "(11) 99999-0000",
    "documento": None,
    "cliente_desde": "2026-10-01T12:00:00+00:00",
    "total_pedidos": 2,
    "valor_total_pedidos": "398.90",
    "total_chamados": 1,
    "id_loja_preferida": ID_LOJA,
    "loja_preferida": "Casa Lorenzi Centro",
}

CARRINHO = {
    "itens": [
        {
            "id_carrinho": ID_CARRINHO,
            "id_variacao": ID_VARIACAO,
            "sku": "CL-CAM-LIN-BR-P",
            "produto": "Camisa Linho Essencial",
            "imagem_url": "/img/produtos/CL-0101.jpg",
            "imagem_alt": "Camisa Linho Essencial",
            "tecido": "em linho lavado",
            "cor": "Branco",
            "tamanho": "P",
            "quantidade": 2,
            "preco_unitario": "149.90",
            "valor_total": "299.80",
        }
    ],
    "subtotal": "299.80",
}


def usar_cliente(app):
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id_auth=ID_AUTH,
        papel=None,
        id_loja=None,
    )


def usar_executor(app, executor):
    app.dependency_overrides[get_executar] = lambda: executor


def devolve(resultado):
    return lambda _operacao: resultado


def executa_operacao(_resultado_ignorado=None):
    return lambda operacao: operacao(None)


def test_rotas_do_cliente_estao_registradas(app, cliente):
    usar_cliente(app)
    caminhos = cliente.get("/openapi.json").json()["paths"]
    registradas = {
        (metodo.upper(), caminho) for caminho, itens in caminhos.items() for metodo in itens
    }
    assert ("GET", "/api/v1/cliente/lojas") in registradas
    assert ("GET", "/api/v1/cliente/perfil") in registradas
    assert ("GET", "/api/v1/cliente/pedidos") in registradas
    assert ("POST", "/api/v1/cliente/pedidos") in registradas
    assert ("GET", "/api/v1/cliente/pedidos/{id_pedido}") in registradas
    assert ("GET", "/api/v1/cliente/carrinho") in registradas
    assert ("POST", "/api/v1/cliente/carrinho/itens") in registradas
    assert ("PATCH", "/api/v1/cliente/carrinho/itens/{id_variacao}") in registradas
    assert ("DELETE", "/api/v1/cliente/carrinho/itens/{id_variacao}") in registradas
    assert ("DELETE", "/api/v1/cliente/carrinho") in registradas
    assert ("GET", "/api/v1/cliente/chamados/opcoes") in registradas
    assert ("GET", "/api/v1/cliente/chamados") in registradas
    assert ("POST", "/api/v1/cliente/chamados") in registradas
    assert ("GET", "/api/v1/cliente/chamados/{id_atendimento}") in registradas
    assert ("GET", "/api/v1/cliente/chamados/{id_atendimento}/mensagens") in registradas
    assert ("POST", "/api/v1/cliente/chamados/{id_atendimento}/mensagens") in registradas


def test_perfil_do_cliente_responde_200(app, cliente):
    usar_cliente(app)
    usar_executor(app, devolve(PERFIL))
    resposta = cliente.get("/api/v1/cliente/perfil")
    assert resposta.status_code == 200
    assert resposta.json()["email"] == "cliente@casalorenzi.test"
    assert resposta.json()["total_pedidos"] == 2


def test_listar_pedidos_do_cliente_responde_200(app, cliente):
    usar_cliente(app)
    usar_executor(app, devolve([PEDIDO]))
    resposta = cliente.get("/api/v1/cliente/pedidos")
    assert resposta.status_code == 200
    assert resposta.json()[0]["numero_pedido"] == "PD-20261007-ABCD1234"


def test_fechar_pedido_do_cliente_responde_201(app, cliente):
    usar_cliente(app)
    usar_executor(app, devolve(PEDIDO))
    resposta = cliente.post(
        "/api/v1/cliente/pedidos",
        headers={"Idempotency-Key": "tentativa-1"},
        json={
            "id_loja": ID_LOJA,
            "entrega": "casa",
            "metodo_pagamento": "pix",
            "frete": "49.00",
            "itens": [{"id_variacao": ID_VARIACAO, "quantidade": 1}],
        },
    )
    assert resposta.status_code == 201
    assert resposta.json()["itens"][0]["sku"] == "CL-CAM-LIN-BR-P"


def test_listar_carrinho_do_cliente_responde_200(app, cliente):
    usar_cliente(app)
    usar_executor(app, devolve(CARRINHO))
    resposta = cliente.get("/api/v1/cliente/carrinho")
    assert resposta.status_code == 200
    assert resposta.json()["subtotal"] == "299.80"
    assert resposta.json()["itens"][0]["imagem_url"] == "/img/produtos/CL-0101.jpg"


def test_adicionar_item_ao_carrinho_responde_201(app, cliente):
    usar_cliente(app)
    usar_executor(app, devolve(CARRINHO))
    resposta = cliente.post(
        "/api/v1/cliente/carrinho/itens",
        json={"id_variacao": ID_VARIACAO, "quantidade": 2},
    )
    assert resposta.status_code == 201
    assert resposta.json()["itens"][0]["quantidade"] == 2


def test_atualizar_item_do_carrinho_responde_200(app, cliente):
    usar_cliente(app)
    usar_executor(app, devolve(CARRINHO))
    resposta = cliente.patch(
        f"/api/v1/cliente/carrinho/itens/{ID_VARIACAO}",
        json={"quantidade": 2},
    )
    assert resposta.status_code == 200
    assert resposta.json()["itens"][0]["sku"] == "CL-CAM-LIN-BR-P"


def test_carrinho_nao_aceita_id_cliente_no_corpo(app, cliente):
    usar_cliente(app)
    resposta = cliente.post(
        "/api/v1/cliente/carrinho/itens",
        json={"id_cliente": "nao-pode-vir-do-front", "id_variacao": ID_VARIACAO, "quantidade": 1},
    )
    assert resposta.status_code == 422


def test_checkout_nao_aceita_id_cliente_no_corpo(app, cliente):
    usar_cliente(app)
    resposta = cliente.post(
        "/api/v1/cliente/pedidos",
        json={
            "id_cliente": "nao-pode-vir-do-front",
            "id_loja": ID_LOJA,
            "entrega": "casa",
            "metodo_pagamento": "pix",
            "itens": [{"id_variacao": ID_VARIACAO, "quantidade": 1}],
        },
    )
    assert resposta.status_code == 422


def test_listar_chamados_do_cliente_responde_200(app, cliente):
    usar_cliente(app)
    usar_executor(app, devolve([CHAMADO]))
    resposta = cliente.get("/api/v1/cliente/chamados")
    assert resposta.status_code == 200
    assert resposta.json()[0]["protocolo"] == "AT-2026-0001"


def test_abrir_chamado_do_cliente_responde_201(app, cliente):
    usar_cliente(app)
    usar_executor(app, devolve(CHAMADO))
    resposta = cliente.post(
        "/api/v1/cliente/chamados",
        json={
            "assunto": "Troca de tamanho",
            "categoria": "troca_devolucao",
            "descricao": "Preciso trocar o tamanho.",
            "id_loja": ID_LOJA,
            "id_pedido": ID_PEDIDO,
            "id_item_pedido": ID_ITEM,
        },
    )
    assert resposta.status_code == 201
    assert resposta.json()["pecas"][0]["sku"] == "CL-CAM-LIN-BR-P"


def test_chamado_nao_aceita_identidade_nem_status_no_corpo(app, cliente):
    usar_cliente(app)
    resposta = cliente.post(
        "/api/v1/cliente/chamados",
        json={
            "assunto": "Troca de tamanho",
            "categoria": "troca_devolucao",
            "descricao": "Preciso trocar o tamanho.",
            "id_cliente": "nao-pode-vir-do-front",
            "id_usuario_remetente": "nao-pode-vir-do-front",
            "id_status_atendimento": "nao-pode-vir-do-front",
        },
    )
    assert resposta.status_code == 422


def test_enviar_mensagem_no_chamado_responde_201(app, cliente):
    usar_cliente(app)
    usar_executor(app, devolve(MENSAGEM))
    resposta = cliente.post(
        f"/api/v1/cliente/chamados/{ID_CHAMADO}/mensagens",
        json={"texto": "  Preciso trocar o tamanho.  "},
    )
    assert resposta.status_code == 201
    assert resposta.json()["texto"] == "Preciso trocar o tamanho."


def test_mensagem_de_chamado_vazia_e_rejeitada(app, cliente):
    usar_cliente(app)
    resposta = cliente.post(
        f"/api/v1/cliente/chamados/{ID_CHAMADO}/mensagens",
        json={"texto": "   "},
    )
    assert resposta.status_code == 422


def test_usuario_interno_nao_acessa_area_do_cliente(app, cliente):
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id_auth=ID_AUTH,
        papel=Papel.OPERADOR_ESTOQUE,
        id_loja=UUID(ID_LOJA),
    )
    usar_executor(app, executa_operacao())
    resposta = cliente.get("/api/v1/cliente/pedidos")
    assert resposta.status_code == 403
    resposta = cliente.get("/api/v1/cliente/chamados")
    assert resposta.status_code == 403
    resposta = cliente.get("/api/v1/cliente/carrinho")
    assert resposta.status_code == 403
