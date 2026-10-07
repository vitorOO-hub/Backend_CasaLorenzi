"""Configuracao da aplicacao, lida de variaveis de ambiente e do arquivo .env."""

from typing import Annotated, Self

from fastapi import Request
from pydantic import SecretStr, field_validator, model_validator
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
    # Liga a trava de autenticacao em app/api/router.py. Desligada por padrao enquanto o
    # front do cliente ainda nao envia o JWT do Supabase.
    autenticacao_obrigatoria: bool = False

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

    @model_validator(mode="after")
    def _exigir_supabase_url_com_autenticacao(self) -> Self:
        if self.autenticacao_obrigatoria and not self.supabase_url:
            raise ValueError(
                "SUPABASE_URL e obrigatoria quando AUTENTICACAO_OBRIGATORIA esta ligada"
            )
        return self


def get_settings(request: Request) -> Settings:
    """Dependencia do FastAPI: as configuracoes com que o app foi criado."""
    return request.app.state.settings
