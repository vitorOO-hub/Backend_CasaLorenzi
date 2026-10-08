"""Gestao do admin contra um Postgres real: ver o time e mudar cargo, unidade e acesso."""

import pytest

from app.core.erros_auth import SemPermissao
from app.core.papeis import Papel, UsuarioAtual
from app.gestao import service
from app.gestao.erros import (
    LojaDoUsuarioInvalida,
    NaoPodeMudarOProprioAcesso,
    UltimoAdministrador,
    UsuarioNaoEncontrado,
)
from app.gestao.schemas import MudancaDeUsuario
from tests.banco.test_chat_repositorio import SemCommit

pytestmark = pytest.mark.banco


class SemCommitNemRollback(SemCommit):
    """Em producao o service desfaz a transacao ao falhar; no teste isso apagaria o cenario."""

    def rollback(self) -> None:
        pass


@pytest.fixture
def sa_conn(sa_conn):
    return SemCommitNemRollback(sa_conn)


def como(usuario, papel=Papel.ADMIN):
    return UsuarioAtual(id_auth=usuario.auth, papel=papel)


def muda(**campos):
    return MudancaDeUsuario(**campos)


def desativar_outros_admins(conn, manter):
    conn.exec_driver_sql(
        "UPDATE usuario SET ativo = false WHERE id_usuario <> %s AND id_tipo_usuario = "
        "(SELECT id_tipo_usuario FROM tipo_usuario WHERE codigo = 'diretor')",
        (manter.id,),
    )


def test_so_o_admin_ve_o_time_e_cliente_nunca_aparece(sa_conn, fab_sa):
    loja = fab_sa.loja()
    admin = fab_sa.usuario("diretor")
    ana = fab_sa.usuario("atendente", loja=loja)
    cliente = fab_sa.usuario("cliente")
    for papel in (Papel.GERENTE_LOJA, Papel.ATENDENTE, Papel.OPERADOR_ESTOQUE):
        with pytest.raises(SemPermissao):
            service.montar_equipe(sa_conn, como(ana, papel))
    equipe = service.montar_equipe(sa_conn, como(admin))
    por_id = {str(i["id_usuario"]): i for i in equipe["itens"]}
    assert str(cliente.id) not in por_id
    assert por_id[str(admin.id)]["cargo"] == "admin" and por_id[str(admin.id)]["id_loja"] is None
    assert por_id[str(ana.id)]["cargo"] == "atendente"
    assert por_id[str(ana.id)]["id_loja"] == loja and por_id[str(ana.id)]["loja_nome"]
    assert {c["codigo"] for c in equipe["opcoes"]["cargos"]} == {
        "admin",
        "atendente",
        "gerente_loja",
        "operador_estoque",
    }
    assert str(loja) in {str(x["id_loja"]) for x in equipe["opcoes"]["lojas"]}
    assert equipe["total"] == len(equipe["itens"])


def test_mudar_cargo_unidade_e_acesso(sa_conn, fab_sa):
    loja_a, loja_b = fab_sa.loja(), fab_sa.loja()
    admin = fab_sa.usuario("diretor")
    ana = fab_sa.usuario("atendente", loja=loja_a)

    r = service.mudar_usuario(sa_conn, como(admin), ana.id, muda(id_loja=loja_b))
    assert r["id_loja"] == loja_b and r["cargo"] == "atendente"
    r = service.mudar_usuario(sa_conn, como(admin), ana.id, muda(cargo="gerente_loja"))
    assert r["cargo"] == "gerente_loja" and r["id_loja"] == loja_b  # a unidade fica
    r = service.mudar_usuario(sa_conn, como(admin), ana.id, muda(ativo=False))
    assert r["ativo"] is False and r["cargo"] == "gerente_loja"
    r = service.mudar_usuario(sa_conn, como(admin), ana.id, muda(cargo="admin", ativo=True))
    assert r["cargo"] == "admin" and r["id_loja"] is None and r["ativo"] is True  # admin: sem loja
    r = service.mudar_usuario(sa_conn, como(admin), ana.id, muda(cargo="atendente", id_loja=loja_a))
    assert r["cargo"] == "atendente" and r["id_loja"] == loja_a


def test_cargo_de_loja_exige_loja_ativa(sa_conn, fab_sa):
    admin = fab_sa.usuario("diretor")
    outro_admin = fab_sa.usuario("diretor")
    fechada = fab_sa.loja(ativa=False)
    with pytest.raises(LojaDoUsuarioInvalida):  # admin virando atendente sem escolher a loja
        service.mudar_usuario(sa_conn, como(admin), outro_admin.id, muda(cargo="atendente"))
    with pytest.raises(LojaDoUsuarioInvalida):
        service.mudar_usuario(
            sa_conn, como(admin), outro_admin.id, muda(cargo="atendente", id_loja=fechada)
        )


def test_so_mexe_no_time_interno(sa_conn, fab_sa):
    admin = fab_sa.usuario("diretor")
    cliente = fab_sa.usuario("cliente")
    with pytest.raises(UsuarioNaoEncontrado):
        service.mudar_usuario(sa_conn, como(admin), cliente.id, muda(ativo=False))
    with pytest.raises(SemPermissao):
        service.mudar_usuario(
            sa_conn, como(admin, Papel.GERENTE_LOJA), cliente.id, muda(ativo=False)
        )


def test_nao_deixa_trancar_a_propria_conta_nem_ficar_sem_admin(sa_conn, fab_sa):
    admin = fab_sa.usuario("diretor")
    outro = fab_sa.usuario("diretor")
    loja = fab_sa.loja()
    # Sem se desativar nem se rebaixar.
    with pytest.raises(NaoPodeMudarOProprioAcesso):
        service.mudar_usuario(sa_conn, como(admin), admin.id, muda(ativo=False))
    with pytest.raises(NaoPodeMudarOProprioAcesso):
        service.mudar_usuario(sa_conn, como(admin), admin.id, muda(cargo="atendente", id_loja=loja))
    # O ultimo administrador ativo nao sai, mesmo vindo de outra conta.
    desativar_outros_admins(sa_conn, manter=outro)
    chamador = UsuarioAtual(id_auth=admin.auth, papel=Papel.ADMIN)
    with pytest.raises(UltimoAdministrador):
        service.mudar_usuario(sa_conn, chamador, outro.id, muda(ativo=False))
    with pytest.raises(UltimoAdministrador):
        service.mudar_usuario(sa_conn, chamador, outro.id, muda(cargo="atendente", id_loja=loja))
