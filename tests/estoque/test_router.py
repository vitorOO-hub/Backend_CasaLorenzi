"""Testes das rotas de estoque sem banco: a dependencia `executar` e trocada por um dublê."""

from types import SimpleNamespace
from uuid import UUID

import pytest

from app.core.db import get_executar
from app.core.papeis import Papel
from app.core.security import get_current_user
from app.estoque.erros import (
    EstoqueInsuficiente,
    RegistroNaoEncontrado,
)

ID_UUID = "6f1c3a52-6a4e-4c8e-9a39-0f1f2b6f2f10"
LINHA = {"id_estoque": ID_UUID, "quantidade": 8}

ROTAS_ESPERADAS = {
    ("GET", "/health"),
    ("GET", "/estoques"),
    ("GET", "/estoques/{id_estoque}"),
    ("POST", "/estoques/{id_estoque}/entrada"),
    ("POST", "/estoques/{id_estoque}/saida"),
    ("POST", "/estoques/{id_estoque}/ajuste"),
}

ROTAS_NAO_PERMITIDAS_OPERADOR = {
    ("POST", "/estoques"),
    ("DELETE", "/estoques/{id_estoque}"),
    ("PATCH", "/estoques/{id_estoque}/minimo"),
}


@pytest.fixture(autouse=True)
def liberar_operador_de_estoque(app):
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id_auth=UUID(ID_UUID),
        id_loja=UUID(ID_UUID),
        papel=Papel.OPERADOR_ESTOQUE,
    )


def usar_executor(app, executor):
    app.dependency_overrides[get_executar] = lambda: executor


def devolve(resultado):
    return lambda _operacao: resultado


def levanta(erro):
    def executor(_operacao):
        raise erro

    return executor


def test_todas_as_rotas_do_estoque_estao_registradas(cliente):
    caminhos = cliente.get("/openapi.json").json()["paths"]
    registradas = {
        (metodo.upper(), caminho) for caminho, itens in caminhos.items() for metodo in itens
    }
    assert ROTAS_ESPERADAS.issubset(registradas)
    assert ROTAS_NAO_PERMITIDAS_OPERADOR.isdisjoint(registradas)


def test_listar_devolve_o_que_o_repositorio_devolve(app, cliente):
    usar_executor(app, devolve([LINHA]))
    resposta = cliente.get("/estoques")
    assert resposta.status_code == 200
    assert resposta.json() == [LINHA]


@pytest.mark.parametrize(
    ("metodo", "caminho", "corpo"),
    [
        ("GET", f"/estoques/{ID_UUID}", None),
        ("POST", f"/estoques/{ID_UUID}/entrada", {"quantidade": 1}),
        ("POST", f"/estoques/{ID_UUID}/saida", {"quantidade": 1}),
        ("POST", f"/estoques/{ID_UUID}/ajuste", {"quantidade": 1}),
    ],
)
def test_registro_inexistente_responde_404(app, cliente, metodo, caminho, corpo):
    usar_executor(app, levanta(RegistroNaoEncontrado()))
    resposta = cliente.request(metodo, caminho, json=corpo)
    assert resposta.status_code == 404
    assert resposta.json() == {"detail": "Estoque nao encontrado"}


def test_saida_maior_que_o_saldo_responde_409(app, cliente):
    usar_executor(app, levanta(EstoqueInsuficiente()))
    resposta = cliente.post(f"/estoques/{ID_UUID}/saida", json={"quantidade": 99})
    assert resposta.status_code == 409
    assert resposta.json() == {"detail": "Estoque insuficiente para realizar a saida"}


@pytest.mark.parametrize(
    ("caminho", "corpo"),
    [
        ("/estoques/1/saida", {"quantidade": 0}),
        ("/estoques/1/saida", {"quantidade": -3}),
        ("/estoques/1/entrada", {"quantidade": 0}),
        ("/estoques/1/entrada", {}),
        ("/estoques/1/ajuste", {"quantidade": -1}),
        ("/estoques/1/ajuste", {}),
    ],
)
def test_quantidade_invalida_e_rejeitada_antes_do_banco(cliente, caminho, corpo):
    # Sem trocar o executor: se a rota abrisse conexao, o teste falharia (nao ha banco de teste).
    resposta = cliente.post(caminho, json=corpo)
    assert resposta.status_code == 422
