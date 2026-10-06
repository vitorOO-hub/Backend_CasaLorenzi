"""Reune os routers de cada modulo. Um modulo novo entra aqui com uma linha."""

from fastapi import APIRouter

from app.api import health
from app.estoque.router import router as estoque_router

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(estoque_router)
