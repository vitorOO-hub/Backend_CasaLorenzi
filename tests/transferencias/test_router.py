"""Testes das rotas de transferencia e reposicao de estoque sem banco real."""

from types import SimpleNamespace

import pytest

from app.core.db import get_executar
from app.core.security import get_current_user
from app.transferencias.erros import TransferenciaNaoEncontrada

ID_UUID = "6f1c3a52-6a4e-4c8e-9a39-0f1f2b6f2f10"
LINHA = {"id_transferencia_estoque": ID_UUID, "quantidade": 2}


@pytest.fixture(autouse=True)
def liberar_operador_de_estoque(app):
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id_usuario=ID_UUID,
        id_loja=ID_UUID,
        tipo_usuario_codigo="operador_estoque",
    )


def usar_executor(app, executor):
    app.dependency_overrides[get_executar] = lambda: executor


def devolve(resultado):
    return lambda _operacao: resultado


def levanta(erro):
    def executor(_operacao):
        raise erro

    return executor


def test_rotas_de_transferencia_estao_registradas(cliente):
    caminhos = cliente.get("/openapi.json").json()["paths"]
    registradas = {
        (metodo.upper(), caminho) for caminho, itens in caminhos.items() for metodo in itens
    }
    assert ("GET", "/transferencias-estoque") in registradas
    assert ("GET", "/transferencias-estoque/{id_transferencia}") in registradas
    assert ("POST", "/transferencias-estoque") in registradas
    assert ("POST", "/transferencias-estoque/reposicoes") in registradas
    assert ("POST", "/transferencias-estoque/{id_transferencia}/aceitar") in registradas


def test_solicitar_transferencia_responde_201(app, cliente):
    usar_executor(app, devolve(LINHA))
    resposta = cliente.post(
        "/transferencias-estoque",
        json={
            "id_loja_origem": ID_UUID,
            "id_variacao": ID_UUID,
            "quantidade": 2,
            "observacao": "Transferencia para repor vitrine.",
        },
    )
    assert resposta.status_code == 201
    assert resposta.json() == LINHA


def test_solicitar_reposicao_responde_201(app, cliente):
    usar_executor(app, devolve(LINHA))
    resposta = cliente.post(
        "/transferencias-estoque/reposicoes",
        json={"id_variacao": ID_UUID, "quantidade": 2},
    )
    assert resposta.status_code == 201
    assert resposta.json() == LINHA


def test_aceitar_transferencia_responde_200(app, cliente):
    usar_executor(app, devolve(LINHA))
    resposta = cliente.post(f"/transferencias-estoque/{ID_UUID}/aceitar")
    assert resposta.status_code == 200
    assert resposta.json() == LINHA


@pytest.mark.parametrize(
    ("caminho", "corpo"),
    [
        ("/transferencias-estoque", {"id_loja_origem": ID_UUID, "id_variacao": ID_UUID, "quantidade": 0}),
        ("/transferencias-estoque/reposicoes", {"id_variacao": ID_UUID, "quantidade": 0}),
    ],
)
def test_quantidade_invalida_e_rejeitada_antes_do_banco(cliente, caminho, corpo):
    resposta = cliente.post(caminho, json=corpo)
    assert resposta.status_code == 422


def test_operador_sem_loja_responde_409(app, cliente):
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id_usuario=ID_UUID,
        id_loja=None,
        tipo_usuario_codigo="operador_estoque",
    )
    resposta = cliente.post(
        "/transferencias-estoque/reposicoes",
        json={"id_variacao": ID_UUID, "quantidade": 2},
    )
    assert resposta.status_code == 409
    assert resposta.json() == {"detail": "Operador de estoque precisa estar vinculado a uma loja"}


def test_transferencia_inexistente_responde_404(app, cliente):
    usar_executor(app, levanta(TransferenciaNaoEncontrada()))
    resposta = cliente.get(f"/transferencias-estoque/{ID_UUID}")
    assert resposta.status_code == 404
    assert resposta.json() == {"detail": "Transferencia de estoque nao encontrada"}
