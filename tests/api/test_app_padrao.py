"""`uvicorn app.main:app`: o app padrao e criado so quando alguem pede o atributo `app`."""

import importlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

import app.main as principal
from tests.conftest import DATABASE_URL_TESTE


@pytest.fixture
def ambiente_isolado(monkeypatch, tmp_path):
    # tmp_path como diretorio atual: nao existe .env ali, entao o .env real nunca e lido.
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    principal._app_padrao.cache_clear()
    yield
    principal._app_padrao.cache_clear()


def test_importar_o_modulo_nao_exige_configuracao(ambiente_isolado):
    importlib.reload(principal)  # sem DATABASE_URL: nao pode levantar erro


def test_pedir_o_app_sem_configuracao_falha_com_erro_de_validacao(ambiente_isolado):
    with pytest.raises(ValidationError):
        _ = principal.app


def test_app_padrao_usa_o_ambiente_e_e_criado_uma_unica_vez(ambiente_isolado, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL_TESTE)
    app_padrao = principal.app
    assert isinstance(app_padrao, FastAPI)
    assert principal.app is app_padrao
    assert TestClient(app_padrao).get("/health").json() == {"status": "ok"}


def test_atributo_inexistente_continua_dando_attribute_error():
    with pytest.raises(AttributeError):
        _ = principal.nao_existe
