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
    frontend_url: str = "https://projetocasalorenzi.vercel.app"
    # So para o Admin API do Auth (ativar a conta de cliente importado). Segredo do servidor.
    supabase_service_role_key: SecretStr | None = None
    # Chave das automacoes (n8n), enviada no cabecalho X-Chave-Automacao. Sem ela, essas rotas
    # respondem 503.
    chave_automacao: SecretStr | None = None
    # Provedores de LLM dos assistentes (Entrega 4). Opcionais: sem chave, o assistente nao liga.
    gemini_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None
    # Destinos validados no benchmark; variaveis de ambiente podem substitui-los.
    assistente_modelo_rapido: str | None = "groq:openai/gpt-oss-20b"
    assistente_modelo_preciso: str | None = "gemini:gemini-3.5-flash-lite"
    cors_origins: Annotated[list[str], NoDecode] = []
    # /docs, /redoc e /openapi.json mostram o mapa inteiro da API: so ligam de proposito (dev).
    docs_habilitadas: bool = False
    # Limite de requisicoes por minuto (ver app/core/protecoes.py). Desligar so em teste.
    limites_ativos: bool = True
    limite_leitura_por_minuto: int = 120
    limite_escrita_por_minuto: int = 30
    limite_sensivel_por_minuto: int = 10

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

    @field_validator("frontend_url")
    @classmethod
    def _validar_frontend_url(cls, valor: str) -> str:
        url = valor.strip().rstrip("/")
        if not url.startswith(("http://", "https://")):
            raise ValueError("FRONTEND_URL deve comecar com http:// ou https://")
        return url

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _separar_origens(cls, valor: object) -> object:
        if isinstance(valor, str):
            return [origem.strip().rstrip("/") for origem in valor.split(",") if origem.strip()]
        return valor

    @field_validator("assistente_modelo_rapido", "assistente_modelo_preciso")
    @classmethod
    def _validar_destino_assistente(cls, valor: str | None) -> str | None:
        if valor is None or not valor.strip():
            return None
        provedor, separador, modelo = valor.strip().partition(":")
        if not separador or provedor not in {"gemini", "groq"} or not modelo.strip():
            raise ValueError("destino deve estar no formato gemini:modelo ou groq:modelo")
        return f"{provedor}:{modelo.strip()}"


def get_settings(request: Request) -> Settings:
    """Dependencia do FastAPI: as configuracoes com que o app foi criado."""
    return request.app.state.settings
