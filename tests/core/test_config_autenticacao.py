import pytest
from pydantic import ValidationError

from app.core.config import Settings
from tests.conftest import DATABASE_URL_TESTE

VARIAVEIS = ["DATABASE_URL", "SUPABASE_URL", "CORS_ORIGINS", "AUTENTICACAO_OBRIGATORIA"]


@pytest.fixture(autouse=True)
def ambiente_limpo(monkeypatch):
    for nome in VARIAVEIS:
        monkeypatch.delenv(nome, raising=False)


def criar(**valores) -> Settings:
    valores.setdefault("database_url", DATABASE_URL_TESTE)
    return Settings(_env_file=None, **valores)


def test_autenticacao_vem_desligada_por_padrao():
    assert criar().autenticacao_obrigatoria is False


def test_le_a_flag_do_ambiente(monkeypatch):
    monkeypatch.setenv("AUTENTICACAO_OBRIGATORIA", "true")
    monkeypatch.setenv("SUPABASE_URL", "https://abc.supabase.co")
    assert criar().autenticacao_obrigatoria is True


def test_flag_ligada_exige_supabase_url():
    with pytest.raises(ValidationError) as erro:
        criar(autenticacao_obrigatoria=True)
    assert "SUPABASE_URL" in str(erro.value)


def test_flag_ligada_com_supabase_url_e_aceita():
    settings = criar(autenticacao_obrigatoria=True, supabase_url="https://abc.supabase.co/")
    assert settings.autenticacao_obrigatoria is True
    assert settings.supabase_url == "https://abc.supabase.co"


def test_flag_desligada_nao_exige_supabase_url():
    assert criar(autenticacao_obrigatoria=False).supabase_url is None
