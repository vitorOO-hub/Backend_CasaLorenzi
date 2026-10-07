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
    assert ("GET", "/movimentacoes-estoque/{id_movimentacao}") in registradas
    assert ("POST", "/movimentacoes-estoque") not in registradas


def test_movimentacao_inexistente_responde_404(app, cliente):
    usar_executor(app, levanta(MovimentacaoNaoEncontrada()))
    resposta = cliente.get(f"/movimentacoes-estoque/{ID_UUID}")
    assert resposta.status_code == 404
    assert resposta.json() == {"detail": "Movimentacao de estoque nao encontrada"}


