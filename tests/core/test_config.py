import pytest
from pydantic import ValidationError

from app.core.config import Settings
from tests.conftest import DATABASE_URL_TESTE

VARIAVEIS = ["DATABASE_URL", "SUPABASE_URL", "CORS_ORIGINS"]


@pytest.fixture(autouse=True)
def ambiente_limpo(monkeypatch):
    for nome in VARIAVEIS:
        monkeypatch.delenv(nome, raising=False)


def criar(**valores) -> Settings:
    valores.setdefault("database_url", DATABASE_URL_TESTE)
    return Settings(_env_file=None, **valores)


def test_valores_padrao():
    settings = criar()
    assert settings.supabase_url is None
    assert settings.supabase_issuer is None
    assert settings.supabase_jwks_url is None
    assert settings.cors_origins == []


def test_le_variaveis_de_ambiente(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL_TESTE)
    monkeypatch.setenv("SUPABASE_URL", "https://abc.supabase.co/")
    monkeypatch.setenv("CORS_ORIGINS", "https://casa-lorenzi.vercel.app/, http://localhost:5173")
    settings = Settings(_env_file=None)
    assert settings.database_url.get_secret_value() == DATABASE_URL_TESTE
    assert settings.supabase_url == "https://abc.supabase.co"
    assert settings.supabase_issuer == "https://abc.supabase.co/auth/v1"
    assert settings.supabase_jwks_url == "https://abc.supabase.co/auth/v1/.well-known/jwks.json"
    assert settings.cors_origins == ["https://casa-lorenzi.vercel.app", "http://localhost:5173"]


def test_database_url_e_obrigatoria():
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_database_url_precisa_ser_postgresql_e_o_erro_nao_vaza_o_valor():
    with pytest.raises(ValidationError) as erro:
        criar(database_url="mysql://root:segredo-real@localhost/db")
    assert "segredo-real" not in str(erro.value)


def test_database_url_nao_aparece_no_repr():
    assert "senha-de-teste" not in repr(criar())
