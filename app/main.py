"""API da Casa Lorenzi. Execucao: uvicorn app.main:app --reload"""

from functools import lru_cache
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import Settings
from app.core.erros import registrar_tratadores


def criar_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    app = FastAPI(title="Casa Lorenzi API", version="0.1.0")
    app.state.settings = settings

    # CORS so para as origens do front (Vercel e ambiente local), vindas de CORS_ORIGINS.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        max_age=600,
    )
    registrar_tratadores(app)
    app.include_router(api_router)
    return app


@lru_cache
def _app_padrao() -> FastAPI:
    return criar_app()


def __getattr__(nome: str) -> Any:
    
    if nome == "app":
        return _app_padrao()
    raise AttributeError(f"module {__name__!r} has no attribute {nome!r}")
