"""Rotas da gestao do admin (`/api/v1/painel/gestao`): o time interno, com cargo, unidade e acesso.

Sempre exigem token valido e papel de admin, independente de AUTENTICACAO_OBRIGATORIA. Cliente nunca
aparece aqui. Mudancas valem para a pessoa quando o token dela renovar (o cargo vem do token).
"""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.core.db import ExecutarDep
from app.core.papeis import Papel, UsuarioAtual
from app.core.security import requer_papel
from app.gestao import auditoria, catalogo, integracoes, service, vendas_pendentes
from app.gestao.schemas import (
    Auditoria,
    Catalogo,
    DescarteDeVenda,
    Equipe,
    ImportacaoDeVenda,
    Integracoes,
    MapeamentoDeRegistro,
    MudancaDeUsuario,
    NovaPeca,
    PecaAlterada,
    PecaDoCatalogo,
    PecaExcluida,
    RegistroImportado,
    UsuarioDaEquipe,
    VendaPendenteDetalhe,
    VendasImportacaoPendentes,
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


@router.get(
    "/vendas-pendentes",
    response_model=VendasImportacaoPendentes,
    summary="Vendas do Vulto aguardando resolucao",
)
def vendas_aguardando_resolucao(
    usuario: AdminDep,
    executar: ExecutarDep,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    grupo: Literal[vendas_pendentes.GRUPOS] | None = None,  # type: ignore[valid-type]
    estado: Literal["pendente", "importada", "descartada"] = "pendente",
):
    def operacao(conexao):
        lista = vendas_pendentes.listar(
            conexao, usuario, limit=limit, offset=offset, grupo=grupo, estado=estado
        )
        return {**lista, "por_grupo": vendas_pendentes.resumo_por_grupo(conexao, usuario, estado)}

    return executar(operacao)


@router.get(
    "/vendas-pendentes/{id_venda}",
    response_model=VendaPendenteDetalhe,
    summary="Uma venda do Vulto aguardando resolucao, sem dados pessoais",
)
def venda_pendente(id_venda: UUID, usuario: AdminDep, executar: ExecutarDep):
    return executar(lambda conexao: vendas_pendentes.detalhe(conexao, usuario, id_venda))


def _confirmando(operacao):
    def com_commit(conexao):
        try:
            resposta = operacao(conexao)
            conexao.commit()
            return resposta
        except Exception:
            conexao.rollback()
            raise

    return com_commit


@router.post(
    "/vendas-pendentes/{id_venda}/importar",
    response_model=VendaPendenteDetalhe,
    summary="Importar a venda como pedido, com o cliente e as pecas escolhidos",
)
def importar_venda_pendente(
    id_venda: UUID, dados: ImportacaoDeVenda, usuario: AdminDep, executar: ExecutarDep
):
    return executar(_confirmando(lambda c: vendas_pendentes.importar(c, usuario, id_venda, dados)))


@router.post(
    "/vendas-pendentes/{id_venda}/descartar",
    response_model=VendaPendenteDetalhe,
    summary="Descartar a venda, com o porque",
)
def descartar_venda_pendente(
    id_venda: UUID, dados: DescarteDeVenda, usuario: AdminDep, executar: ExecutarDep
):
    return executar(
        _confirmando(lambda c: vendas_pendentes.descartar(c, usuario, id_venda, dados.observacao))
    )


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
