"""Reune os routers de cada modulo. Um modulo novo entra aqui com uma linha.

Todo router exige token valido e papel por conta propria (`requer_papel` ou `get_current_user`); nao
existe modo aberto. O teste `tests/api/test_todas_as_rotas_exigem_login.py` quebra se uma rota nova
esquecer isso.
"""

from fastapi import APIRouter

from app.api import health
from app.chamados.router import router as chamados_router
from app.chat.router import router as chat_router
from app.cliente.router import router as cliente_router
from app.clientes.router import router as clientes_router
from app.dashboard.router import router as dashboard_router
from app.gerencia.router import router as gerencia_router
from app.gestao.router import router as gestao_router
from app.painel_estoque.router import router as painel_estoque_router

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(dashboard_router)
# Area do painel e do cliente, em /api/v1 (o prefixo que o cliente HTTP do front espera).
api_router.include_router(chamados_router, prefix="/api/v1")
api_router.include_router(chat_router, prefix="/api/v1")
api_router.include_router(gerencia_router, prefix="/api/v1")
api_router.include_router(gestao_router, prefix="/api/v1")
api_router.include_router(painel_estoque_router, prefix="/api/v1")
api_router.include_router(cliente_router, prefix="/api/v1")
api_router.include_router(clientes_router, prefix="/api/v1")
