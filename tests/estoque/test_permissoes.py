"""Testes de permissao para o fluxo do operador de estoque."""

from types import SimpleNamespace

from app.core.db import get_executar
from app.core.security import get_current_user


def test_estoque_sem_token_responde_401(cliente):
    resposta = cliente.get("/estoques")
    assert resposta.status_code == 401
    assert resposta.json() == {"detail": "Token invalido ou expirado"}
    assert resposta.headers["www-authenticate"] == "Bearer"


def test_operador_de_estoque_acessa_estoques(app, cliente):
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        tipo_usuario_codigo="operador_estoque"
    )
    app.dependency_overrides[get_executar] = lambda: lambda _operacao: []
    resposta = cliente.get("/estoques")
    assert resposta.status_code == 200
    assert resposta.json() == []


def test_movimentacoes_sem_token_responde_401(cliente):
    resposta = cliente.get("/movimentacoes-estoque")
    assert resposta.status_code == 401
    assert resposta.json() == {"detail": "Token invalido ou expirado"}


def test_transferencias_sem_token_responde_401(cliente):
    resposta = cliente.get("/transferencias-estoque")
    assert resposta.status_code == 401
    assert resposta.json() == {"detail": "Token invalido ou expirado"}


def test_operador_de_estoque_acessa_transferencias(app, cliente):
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id_usuario="6f1c3a52-6a4e-4c8e-9a39-0f1f2b6f2f10",
        id_loja="6f1c3a52-6a4e-4c8e-9a39-0f1f2b6f2f10",
        tipo_usuario_codigo="operador_estoque",
    )
    app.dependency_overrides[get_executar] = lambda: lambda _operacao: []
    resposta = cliente.get("/transferencias-estoque")
    assert resposta.status_code == 200
    assert resposta.json() == []
