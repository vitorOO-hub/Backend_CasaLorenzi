"""Reune os routers de cada modulo. Um modulo novo entra aqui com uma linha."""

from fastapi import APIRouter, Depends

from app.admin.router import router as admin_router
from app.api import health
from app.atendimento.router import router as atendimento_router
from app.compras.router import router as compras_router
from app.core.papeis import Papel
from app.core.security import trava
from app.estoque.router import router as estoque_router
from app.movimentacoes.router import router as movimentacoes_router

# So atua com AUTENTICACAO_OBRIGATORIA=true (ver app/core/security.py). Barra acesso anonimo e
# papel inadequado; filtro por dono ou por loja continua dentro dos handlers de cada modulo.
EQUIPE_DE_ESTOQUE = (Papel.OPERADOR_ESTOQUE, Papel.GERENTE_LOJA, Papel.ADMIN)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(admin_router, dependencies=[Depends(trava(Papel.ADMIN))])
api_router.include_router(atendimento_router, dependencies=[Depends(trava())])
api_router.include_router(compras_router, dependencies=[Depends(trava())])
api_router.include_router(estoque_router, dependencies=[Depends(trava(*EQUIPE_DE_ESTOQUE))])
api_router.include_router(
    movimentacoes_router, dependencies=[Depends(trava(*EQUIPE_DE_ESTOQUE))]
)
