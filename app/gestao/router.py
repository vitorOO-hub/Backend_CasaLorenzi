"""Rotas da gestao do admin (`/api/v1/painel/gestao`): o time interno, com cargo, unidade e acesso.

Sempre exigem token valido e papel de admin, independente de AUTENTICACAO_OBRIGATORIA. Cliente nunca
aparece aqui. Mudancas valem para a pessoa quando o token dela renovar (o cargo vem do token).
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.core.db import ExecutarDep
from app.core.papeis import Papel, UsuarioAtual
from app.core.security import requer_papel
from app.gestao import service
from app.gestao.schemas import Equipe, MudancaDeUsuario, UsuarioDaEquipe

router = APIRouter(prefix="/painel/gestao", tags=["painel-gestao"])

AdminDep = Annotated[UsuarioAtual, Depends(requer_papel(Papel.ADMIN))]


@router.get("/usuarios", response_model=Equipe, summary="Time interno: cargo, unidade e acesso")
def usuarios(usuario: AdminDep, executar: ExecutarDep):
    return executar(lambda conexao: service.montar_equipe(conexao, usuario))


@router.patch(
    "/usuarios/{id_usuario}",
    response_model=UsuarioDaEquipe,
    summary="Mudar cargo, unidade ou acesso de uma pessoa do time",
)
def mudar_usuario(
    id_usuario: UUID, dados: MudancaDeUsuario, usuario: AdminDep, executar: ExecutarDep
):
    return executar(lambda conexao: service.mudar_usuario(conexao, usuario, id_usuario, dados))
