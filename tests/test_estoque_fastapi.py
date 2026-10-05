from fastapi.testclient import TestClient

from estoque_fastapi.app import criar_app
from estoque_fastapi.config import Configuracao


def cliente_teste() -> TestClient:
    app = criar_app(Configuracao(database_url="postgresql://usuario:senha@localhost:5432/postgres"))
    return TestClient(app)


def test_health_fastapi():
    cliente = cliente_teste()
    resposta = cliente.get("/health")
    assert resposta.status_code == 200
    assert resposta.json() == {"status": "ok"}


def test_saida_rejeita_quantidade_zero_antes_do_banco():
    cliente = cliente_teste()
    resposta = cliente.post("/estoques/1/saida", json={"quantidade": 0})
    assert resposta.status_code == 422
