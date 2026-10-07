"""Testes das rotas de movimentacao de estoque sem banco real."""

from app.core.db import get_executar
from app.movimentacoes.erros import MovimentacaoNaoEncontrada

ID_UUID = "6f1c3a52-6a4e-4c8e-9a39-0f1f2b6f2f10"
LINHA = {"id_movimentacao_estoque": ID_UUID, "quantidade": 2}


def usar_executor(app, executor):
    app.dependency_overrides[get_executar] = lambda: executor


def devolve(resultado):
    return lambda _operacao: resultado


def levanta(erro):
    def executor(_operacao):
        raise erro

    return executor


def test_rotas_de_movimentacao_estao_registradas(cliente):
    caminhos = cliente.get("/openapi.json").json()["paths"]
    registradas = {
        (metodo.upper(), caminho) for caminho, itens in caminhos.items() for metodo in itens
    }
    assert ("GET", "/movimentacoes-estoque") in registradas
    assert ("POST", "/movimentacoes-estoque") in registradas
    assert ("GET", "/movimentacoes-estoque/{id_movimentacao}") in registradas


def test_criar_movimentacao_responde_201(app, cliente):
    usar_executor(app, devolve(LINHA))
    resposta = cliente.post(
        "/movimentacoes-estoque",
        json={
            "id_loja": ID_UUID,
            "id_variacao": ID_UUID,
            "id_tipo_movimentacao_estoque": ID_UUID,
            "quantidade": 2,
            "quantidade_anterior": 10,
            "quantidade_posterior": 8,
        },
    )
    assert resposta.status_code == 201
    assert resposta.json() == LINHA


def test_criar_movimentacao_rejeita_quantidade_invalida(cliente):
    resposta = cliente.post(
        "/movimentacoes-estoque",
        json={
            "id_loja": ID_UUID,
            "id_variacao": ID_UUID,
            "id_tipo_movimentacao_estoque": ID_UUID,
            "quantidade": 0,
            "quantidade_anterior": 10,
            "quantidade_posterior": 10,
        },
    )
    assert resposta.status_code == 422


def test_movimentacao_inexistente_responde_404(app, cliente):
    usar_executor(app, levanta(MovimentacaoNaoEncontrada()))
    resposta = cliente.get(f"/movimentacoes-estoque/{ID_UUID}")
    assert resposta.status_code == 404
    assert resposta.json() == {"detail": "Movimentacao de estoque nao encontrada"}


def test_movimentacao_invalida_responde_409(app, cliente, erro_integridade):
    usar_executor(app, levanta(erro_integridade("23514")))
    resposta = cliente.post(
        "/movimentacoes-estoque",
        json={
            "id_loja": ID_UUID,
            "id_variacao": ID_UUID,
            "id_tipo_movimentacao_estoque": ID_UUID,
            "quantidade": 2,
            "quantidade_anterior": 10,
            "quantidade_posterior": 10,
        },
    )
    assert resposta.status_code == 409
    assert resposta.json() == {"detail": "Movimentacao de estoque invalida para os dados informados"}
