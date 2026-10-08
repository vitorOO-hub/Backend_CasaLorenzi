import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.main import criar_app

# Os testes disparam centenas de chamadas por segundo; os do limite ligam por conta propria.
os.environ.setdefault("LIMITES_ATIVOS", "false")

DATABASE_URL_TESTE = "postgresql://usuario:senha-de-teste@localhost:5432/postgres"


class ErroBancoFalso(Exception):
    def __init__(self, sqlstate: str):
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


@pytest.fixture
def settings() -> Settings:
    # _env_file=None: os testes nunca leem o .env real.
    return Settings(
        _env_file=None,
        database_url=DATABASE_URL_TESTE,
        cors_origins=["http://localhost:5173"],
    )


@pytest.fixture
def app(settings):
    return criar_app(settings)


@pytest.fixture
def cliente(app) -> TestClient:
    return TestClient(app)


@pytest.fixture
def erro_integridade():
    def montar(sqlstate: str) -> IntegrityError:
        return IntegrityError("SQL", {}, ErroBancoFalso(sqlstate))

    return montar


@pytest.fixture(autouse=True)
def _sem_conferencia_de_vigencia(monkeypatch):
    """A maioria dos testes simula o banco; a conferencia de vigencia tem testes proprios."""
    from app.core import vigencia

    monkeypatch.setattr(vigencia, "ATIVA", False)
