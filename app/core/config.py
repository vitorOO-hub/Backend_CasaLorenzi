"""Configuracao da aplicacao, lida de variaveis de ambiente e do arquivo .env."""

from typing import Annotated

from fastapi import Request
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    # hide_input_in_errors: um valor invalido nao pode aparecer na mensagem de erro,
    # porque DATABASE_URL carrega a senha do banco.
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    database_url: SecretStr
    supabase_url: str | None = None
    cors_origins: Annotated[list[str], NoDecode] = []
    # /docs, /redoc e /openapi.json mostram o mapa inteiro da API: so ligam de proposito (dev).
    docs_habilitadas: bool = False
    # Limite de requisicoes por minuto (ver app/core/protecoes.py). Desligar so em teste.
    limites_ativos: bool = True
    limite_leitura_por_minuto: int = 120
    limite_escrita_por_minuto: int = 30
    limite_sensivel_por_minuto: int = 10
    limite_anonimo_por_minuto: int = 300

    @field_validator("database_url")
    @classmethod
    def _validar_database_url(cls, valor: SecretStr) -> SecretStr:
        if not valor.get_secret_value().startswith(("postgresql://", "postgres://")):
            raise ValueError("DATABASE_URL deve comecar com postgresql://")
        return valor

    @field_validator("supabase_url")
    @classmethod
    def _tirar_barra_final(cls, valor: str | None) -> str | None:
        return valor.strip().rstrip("/") if valor else None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _separar_origens(cls, valor: object) -> object:
        if isinstance(valor, str):
            return [origem.strip().rstrip("/") for origem in valor.split(",") if origem.strip()]
        return valor


def get_settings(request: Request) -> Settings:
    """Dependencia do FastAPI: as configuracoes com que o app foi criado."""
    return request.app.state.settings
