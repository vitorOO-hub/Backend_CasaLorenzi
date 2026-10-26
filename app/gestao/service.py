"""Regras da gestao do admin: ver o time e mudar cargo, unidade e acesso de cada pessoa."""

from typing import Any
from uuid import UUID

from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from app.ativacao.auth_admin import AuthAdmin
from app.ativacao.erros import EmailJaNoAuth
from app.core import vigencia
from app.core.erros_auth import SemPermissao
from app.core.papeis import Papel, UsuarioAtual
from app.gestao import auditoria, repositorio
from app.gestao.erros import (
    CargoNaoPermitido,
    EmailJaCadastrado,
    LojaDoUsuarioInvalida,
    NaoPodeMudarOProprioAcesso,
    UltimoAdministrador,
    UsuarioNaoEncontrado,
)
from app.gestao.schemas import MudancaDeUsuario, NovoUsuarioDaEquipe


def _so_admin(usuario: UsuarioAtual) -> None:
    if usuario.papel is not Papel.ADMIN:
        raise SemPermissao()


def montar_equipe(conexao: Connection, usuario: UsuarioAtual) -> dict[str, Any]:
    if usuario.papel is Papel.ADMIN:
        itens = repositorio.equipe(conexao)
        cargos = repositorio.cargos(conexao)
        lojas = repositorio.lojas_ativas(conexao)
    elif usuario.papel is Papel.GERENTE_LOJA and usuario.id_loja is not None:
        itens = repositorio.equipe(conexao, id_loja=usuario.id_loja)
        cargos = repositorio.cargos(conexao, gerente=True)
        lojas = []
    else:
        raise SemPermissao()
    return {
        "total": len(itens),
        "itens": itens,
        "opcoes": {
            "cargos": cargos,
            "lojas": lojas,
        },
    }


def criar_usuario(
    conexao: Connection,
    auth_admin: AuthAdmin,
    usuario: UsuarioAtual,
    dados: NovoUsuarioDaEquipe,
) -> dict[str, Any]:
    """Cria o registro da equipe e envia um convite de definição de senha pelo Supabase Auth."""
    id_loja = dados.id_loja
    if usuario.papel is Papel.ADMIN:
        if dados.cargo == "admin":
            id_loja = None
        elif id_loja is None or not repositorio.loja_ativa(conexao, id_loja):
            raise LojaDoUsuarioInvalida()
    elif usuario.papel is Papel.GERENTE_LOJA and usuario.id_loja is not None:
        if dados.cargo not in {"atendente", "operador_estoque", "vendedor"}:
            raise CargoNaoPermitido()
        if id_loja is not None and id_loja != usuario.id_loja:
            raise SemPermissao()
        id_loja = usuario.id_loja
    else:
        raise SemPermissao()

    email = str(dados.email).strip().lower()
    if repositorio.email_em_uso(conexao, email):
        raise EmailJaCadastrado()

    id_auth: UUID | None = None
    try:
        id_usuario = repositorio.inserir_usuario(
            conexao,
            nome=dados.nome,
            email=email,
            cargo=dados.cargo,
            id_loja=id_loja,
        )
        if id_usuario is None:
            raise CargoNaoPermitido()
        id_auth = auth_admin.convidar_usuario(email)
        if not repositorio.ligar_auth(conexao, id_usuario, id_auth):
            raise UsuarioNaoEncontrado()
        auditoria.registrar(
            conexao,
            usuario,
            "Convidou funcionario",
            f"{dados.nome} · {dados.cargo}",
        )
        conexao.commit()
    except EmailJaNoAuth as erro:
        conexao.rollback()
        raise EmailJaCadastrado() from erro
    except Exception as erro:
        conexao.rollback()
        if id_auth is not None:
            auth_admin.apagar_usuario(id_auth)
        constraint = getattr(getattr(erro, "orig", None), "diag", None)
        if isinstance(erro, IntegrityError) and getattr(
            constraint, "constraint_name", None
        ) == "uq_usuario_email":
            raise EmailJaCadastrado() from erro
        raise

    novo = repositorio.um_da_equipe(conexao, id_usuario)
    if novo is None:
        raise UsuarioNaoEncontrado()
    return novo


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
