import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.main import criar_app

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
