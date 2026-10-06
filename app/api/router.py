"""Reune os routers de cada modulo. Um modulo novo entra aqui com uma linha."""

from fastapi import APIRouter

from app.api import health
from app.admin.router import router as admin_router
from app.compras.router import router as compras_router
from app.estoque.router import router as estoque_router
from app.movimentacoes.router import router as movimentacoes_router

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(admin_router)
api_router.include_router(compras_router)
api_router.include_router(estoque_router)
api_router.include_router(movimentacoes_router)
