"""API da Casa Lorenzi. Execucao: uvicorn app.main:app --reload"""

from functools import lru_cache
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import Settings
from app.core.erros import registrar_tratadores
from app.core.protecoes import CabecalhosDeSeguranca, LimitadorDeRequisicoes


def criar_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    docs = settings.docs_habilitadas
    app = FastAPI(
        title="Casa Lorenzi API",
        version="0.1.0",
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.state.settings = settings

    # Ordem dos middlewares (o ultimo adicionado e o mais externo): limite -> CORS -> cabecalhos.
    # O CORS envolve o limite para a resposta 429 tambem chegar ao navegador.
    app.add_middleware(
        LimitadorDeRequisicoes,
        ativo=settings.limites_ativos,
        leitura=settings.limite_leitura_por_minuto,
        escrita=settings.limite_escrita_por_minuto,
        sensivel=settings.limite_sensivel_por_minuto,
        anonimo=settings.limite_anonimo_por_minuto,
    )

    # CORS so para as origens do front (Vercel e ambiente local), vindas de CORS_ORIGINS.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
        max_age=600,
    )
    app.add_middleware(CabecalhosDeSeguranca)
    registrar_tratadores(app)
    app.include_router(api_router)
    return app


@lru_cache
def _app_padrao() -> FastAPI:
    return criar_app()


def __getattr__(nome: str) -> Any:
    """Permite `uvicorn app.main:app`, mas o app padrao so e criado quando alguem pede `app`.

    Assim importar `app.main` (como fazem os testes) nao le o .env nem exige DATABASE_URL.
    """
    if nome == "app":
        return _app_padrao()
    raise AttributeError(f"module {__name__!r} has no attribute {nome!r}")
