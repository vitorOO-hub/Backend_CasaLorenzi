"""Testes de permissao para o fluxo do operador de estoque."""

from types import SimpleNamespace
from uuid import UUID

from app.core.db import get_executar
from app.core.papeis import Papel
from app.core.security import get_current_user


def test_operador_de_estoque_acessa_estoques(app, cliente):
    app.dependency_overrides[get_executar] = lambda: lambda _operacao: []
    resposta = cliente.get("/estoques")
    assert resposta.status_code == 200
    assert resposta.json() == []


def test_operador_de_estoque_acessa_transferencias(app, cliente):
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id_auth=UUID("6f1c3a52-6a4e-4c8e-9a39-0f1f2b6f2f10"),
        id_loja=UUID("6f1c3a52-6a4e-4c8e-9a39-0f1f2b6f2f10"),
        papel=Papel.OPERADOR_ESTOQUE,
    )
    app.dependency_overrides[get_executar] = lambda: lambda _operacao: []
    resposta = cliente.get("/transferencias-estoque")
    assert resposta.status_code == 200
    assert resposta.json() == []
