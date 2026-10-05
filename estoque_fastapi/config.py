"""Configuracao do prototipo FastAPI de estoque."""

from dataclasses import dataclass
from os import getenv

from dotenv import load_dotenv


@dataclass(frozen=True)
class Configuracao:
    database_url: str


def carregar_configuracao() -> Configuracao:
    load_dotenv()
    database_url = getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL nao encontrada. Crie um .env local antes de rodar.")
    return Configuracao(database_url=database_url)
