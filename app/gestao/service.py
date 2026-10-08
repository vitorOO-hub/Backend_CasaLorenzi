"""Regras da gestao do admin: ver o time e mudar cargo, unidade e acesso de cada pessoa."""

from typing import Any
from uuid import UUID

from sqlalchemy.engine import Connection

from app.core import vigencia
from app.core.erros_auth import SemPermissao
from app.core.papeis import Papel, UsuarioAtual
from app.gestao import auditoria, repositorio
from app.gestao.erros import (
    LojaDoUsuarioInvalida,
    NaoPodeMudarOProprioAcesso,
    UltimoAdministrador,
    UsuarioNaoEncontrado,
)
from app.gestao.schemas import MudancaDeUsuario


def _so_admin(usuario: UsuarioAtual) -> None:
    if usuario.papel is not Papel.ADMIN:
        raise SemPermissao()


def montar_equipe(conexao: Connection, usuario: UsuarioAtual) -> dict[str, Any]:
    _so_admin(usuario)
    itens = repositorio.equipe(conexao)
    return {
        "total": len(itens),
        "itens": itens,
        "opcoes": {
            "cargos": repositorio.cargos(conexao),
            "lojas": repositorio.lojas_ativas(conexao),
        },
    }


def mudar_usuario(
    conexao: Connection, usuario: UsuarioAtual, id_usuario: UUID, mudanca: MudancaDeUsuario
) -> dict[str, Any]:
    _so_admin(usuario)
    try:
        # Primeiro trava a linha, depois le o estado (a leitura com JOIN nao pode travar).
        travado = repositorio.travar(conexao, id_usuario)
        atual = repositorio.um_da_equipe(conexao, id_usuario)
        if travado is None or atual is None:
            raise UsuarioNaoEncontrado()

        campos = mudanca.model_fields_set
        cargo = mudanca.cargo or atual["cargo"]
        ativo = atual["ativo"] if mudanca.ativo is None else mudanca.ativo
        # Admin enxerga a rede (sem loja); os demais cargos sempre tem uma loja ativa.
        if cargo == "admin":
            id_loja = None
        else:
            id_loja = mudanca.id_loja if "id_loja" in campos else atual["id_loja"]
            if id_loja is None or not repositorio.loja_ativa(conexao, id_loja):
                raise LojaDoUsuarioInvalida()

        sou_eu = travado["auth_user_id"] is not None and travado["auth_user_id"] == usuario.id_auth
        if sou_eu and (not ativo or cargo != "admin"):
            raise NaoPodeMudarOProprioAcesso()
        era_admin_ativo = atual["cargo"] == "admin" and atual["ativo"]
        continua_admin_ativo = cargo == "admin" and ativo
        if era_admin_ativo and not continua_admin_ativo:
            if repositorio.outros_admins_ativos(conexao, id_usuario) == 0:
                raise UltimoAdministrador()

        repositorio.atualizar(conexao, id_usuario, cargo=cargo, id_loja=id_loja, ativo=ativo)
        auditoria.registrar(
            conexao,
            usuario,
            "Alterou usuário",
            f"{atual['nome']} · {cargo}{'' if ativo else ' · desativado'}",
        )
        conexao.commit()
    except Exception:
        conexao.rollback()
        raise
    if travado["auth_user_id"] is not None:
        vigencia.esquecer(travado["auth_user_id"])
    novo = repositorio.um_da_equipe(conexao, id_usuario)
    if novo is None:
        raise UsuarioNaoEncontrado()
    return novo
