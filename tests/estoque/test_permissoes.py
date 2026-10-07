"""Testes de permissao para o fluxo do operador de estoque."""

from types import SimpleNamespace

from app.core.db import get_executar
from app.core.security import get_current_user


def test_estoque_sem_token_responde_401(cliente):
    resposta = cliente.get("/estoques")
    assert resposta.status_code == 401
    assert resposta.json() == {"detail": "Token invalido ou expirado"}
    assert resposta.headers["www-authenticate"] == "Bearer"


def test_estoque_com_perfil_errado_responde_403(app, cliente):
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        tipo_usuario_codigo="cliente"
    )
    resposta = cliente.get("/estoques")
    assert resposta.status_code == 403
    assert resposta.json() == {"detail": "Sem permissao para esta acao"}


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
