"""Rotas da gestao do admin (`/api/v1/painel/gestao`): o time interno, com cargo, unidade e acesso.

Sempre exigem token valido e papel de admin, independente de AUTENTICACAO_OBRIGATORIA. Cliente nunca
aparece aqui. Mudancas valem para a pessoa quando o token dela renovar (o cargo vem do token).
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.core.db import ExecutarDep
from app.core.papeis import Papel, UsuarioAtual
from app.core.security import requer_papel
from app.gestao import auditoria, catalogo, integracoes, service
from app.gestao.schemas import (
    Auditoria,
    Catalogo,
    Equipe,
    Integracoes,
    MapeamentoDeRegistro,
    MudancaDeUsuario,
    NovaPeca,
    PecaAlterada,
    PecaDoCatalogo,
    PecaExcluida,
    RegistroImportado,
    UsuarioDaEquipe,
)

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


Busca = Annotated[str | None, Query(max_length=80)]


@router.get("/catalogo", response_model=Catalogo, summary="Pecas e precos do catalogo")
def pecas(
    usuario: AdminDep,
    executar: ExecutarDep,
    busca: Busca = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return executar(
        lambda conexao: catalogo.listar(conexao, usuario, busca=busca, limit=limit, offset=offset)
    )


@router.post(
    "/catalogo",
    response_model=PecaDoCatalogo,
    status_code=status.HTTP_201_CREATED,
    summary="Nova peca no catalogo",
)
def criar_peca(dados: NovaPeca, usuario: AdminDep, executar: ExecutarDep):
    return executar(lambda conexao: catalogo.criar(conexao, usuario, dados))


@router.patch("/catalogo/{id_produto}", response_model=PecaDoCatalogo, summary="Editar uma peca")
def alterar_peca(id_produto: UUID, dados: PecaAlterada, usuario: AdminDep, executar: ExecutarDep):
    return executar(lambda conexao: catalogo.alterar(conexao, usuario, id_produto, dados))


@router.delete("/catalogo/{id_produto}", response_model=PecaExcluida, summary="Excluir uma peca")
def excluir_peca(id_produto: UUID, usuario: AdminDep, executar: ExecutarDep):
    return executar(lambda conexao: catalogo.excluir(conexao, usuario, id_produto))


@router.get("/auditoria", response_model=Auditoria, summary="Quem fez o que na rede")
def registros_de_auditoria(
    usuario: AdminDep,
    executar: ExecutarDep,
    busca: Busca = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return executar(
        lambda conexao: auditoria.listar(conexao, usuario, busca=busca, limit=limit, offset=offset)
    )


@router.get("/integracoes", response_model=Integracoes, summary="Lotes do ERP e registros a mapear")
def lotes_e_registros(usuario: AdminDep, executar: ExecutarDep):
    return executar(lambda conexao: integracoes.montar(conexao, usuario))


@router.post(
    "/integracoes/registros/{id_registro}/mapear",
    response_model=RegistroImportado,
    summary="Ligar um codigo do ERP a um SKU da Casa Lorenzi",
)
def mapear_registro(
    id_registro: UUID, dados: MapeamentoDeRegistro, usuario: AdminDep, executar: ExecutarDep
):
    return executar(
        lambda conexao: integracoes.mapear(conexao, usuario, id_registro, dados.id_variacao)
    )
