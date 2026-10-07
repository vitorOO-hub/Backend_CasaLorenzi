"""Reune os routers de cada modulo. Um modulo novo entra aqui com uma linha."""

from fastapi import APIRouter, Depends

from app.admin.router import router as admin_router
from app.api import health
from app.atendimento.router import router as atendimento_router
from app.chamados.router import router as chamados_router
from app.chat.router import router as chat_router
from app.cliente.router import router as cliente_router
from app.compras.router import router as compras_router
from app.core.papeis import Papel
from app.core.security import trava
from app.dashboard.router import router as dashboard_router
from app.estoque.router import router as estoque_router
from app.movimentacoes.router import router as movimentacoes_router
from app.transferencias.router import router as transferencias_router

# So atua com AUTENTICACAO_OBRIGATORIA=true (ver app/core/security.py).
# O recorte do operador de estoque deve aceitar somente operador_estoque.
OPERADOR_DE_ESTOQUE = (Papel.OPERADOR_ESTOQUE,)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(admin_router, dependencies=[Depends(trava(Papel.ADMIN))])
api_router.include_router(atendimento_router, dependencies=[Depends(trava())])
api_router.include_router(compras_router, dependencies=[Depends(trava())])
# O dashboard exige token e papel sempre (ver app/dashboard/router.py), sem depender da flag.
api_router.include_router(dashboard_router)
# Area de chamados do painel, em /api/v1 (o prefixo que o cliente HTTP do front espera).
api_router.include_router(chamados_router, prefix="/api/v1")
api_router.include_router(chat_router, prefix="/api/v1")
api_router.include_router(cliente_router, prefix="/api/v1")
api_router.include_router(estoque_router, dependencies=[Depends(trava(*OPERADOR_DE_ESTOQUE))])
api_router.include_router(
    movimentacoes_router,
    dependencies=[Depends(trava(*OPERADOR_DE_ESTOQUE))],
)
api_router.include_router(
    transferencias_router,
    dependencies=[Depends(trava(*OPERADOR_DE_ESTOQUE))],
)
