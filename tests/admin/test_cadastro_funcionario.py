from uuid import uuid4

import pytest

from app.ativacao.erros import EmailJaNoAuth
from app.core.erros_auth import SemPermissao
from app.core.papeis import Papel, UsuarioAtual
from app.gestao import service
from app.gestao.erros import (
    CargoNaoPermitido,
    EmailJaCadastrado,
    LojaDoUsuarioInvalida,
    UsuarioNaoEncontrado,
)
from app.gestao.schemas import NovoUsuarioDaEquipe

ID_AUTH = uuid4()
ID_USUARIO = uuid4()
ID_LOJA = uuid4()


class ConexaoFalsa:
    def __init__(self):
        self.eventos = []

    def commit(self):
        self.eventos.append("commit")

    def rollback(self):
        self.eventos.append("rollback")


class AuthFalso:
    def __init__(self, erro=None):
        self.erro = erro
        self.convidados = []
        self.apagados = []

    def convidar_usuario(self, email):
        if self.erro:
            raise self.erro
        self.convidados.append(email)
        return ID_AUTH

    def apagar_usuario(self, id_auth):
        self.apagados.append(id_auth)


def novo(**campos):
    padrao = {
        "nome": "Ana Souza",
        "email": "ANA.SOUZA@example.com",
        "cargo": "atendente",
        "id_loja": ID_LOJA,
    }
    return NovoUsuarioDaEquipe(**(padrao | campos))


def preparar(monkeypatch, *, id_usuario=ID_USUARIO, email_em_uso=False, ligar=True):
    inseridos = []
    monkeypatch.setattr(service.repositorio, "loja_ativa", lambda *_: True)
    monkeypatch.setattr(service.repositorio, "email_em_uso", lambda *_: email_em_uso)

    def inserir(_conn, **dados):
        inseridos.append(dados)
        return id_usuario

    monkeypatch.setattr(service.repositorio, "inserir_usuario", inserir)
    monkeypatch.setattr(service.repositorio, "ligar_auth", lambda *_: ligar)
    monkeypatch.setattr(
        service.repositorio,
        "um_da_equipe",
        lambda *_: {
            "id_usuario": id_usuario,
            "nome": "ana souza",
            "email": "ana.souza@example.com",
            "cargo": "atendente",
            "id_loja": ID_LOJA,
            "loja_nome": "Loja teste",
            "ativo": True,
            "com_acesso": True,
            "criado_em": "2026-10-26T12:00:00Z",
        },
    )
    monkeypatch.setattr(service.auditoria, "registrar", lambda *_: None)
    return inseridos


def test_admin_cadastra_funcionario_normaliza_email_e_confirma_transacao(monkeypatch):
    inseridos = preparar(monkeypatch)
    conexao, auth = ConexaoFalsa(), AuthFalso()
    admin = UsuarioAtual(id_auth=uuid4(), papel=Papel.ADMIN)

    resposta = service.criar_usuario(conexao, auth, admin, novo())

    assert inseridos[0]["email"] == "ana.souza@example.com"
    assert inseridos[0]["nome"] == "ana souza"
    assert auth.convidados == ["ana.souza@example.com"]
    assert resposta["com_acesso"] is True
    assert conexao.eventos == ["commit"]


def test_admin_cadastra_admin_sem_loja(monkeypatch):
    inseridos = preparar(monkeypatch)
    dados = novo(cargo="admin", id_loja=None)
    admin = UsuarioAtual(id_auth=uuid4(), papel=Papel.ADMIN)

    service.criar_usuario(ConexaoFalsa(), AuthFalso(), admin, dados)

    assert inseridos[0]["cargo"] == "admin"
    assert inseridos[0]["id_loja"] is None


def test_admin_nao_cadastra_cargo_de_loja_sem_loja_ativa(monkeypatch):
    monkeypatch.setattr(service.repositorio, "loja_ativa", lambda *_: False)
    admin = UsuarioAtual(id_auth=uuid4(), papel=Papel.ADMIN)

    with pytest.raises(LojaDoUsuarioInvalida):
        service.criar_usuario(ConexaoFalsa(), AuthFalso(), admin, novo())


def test_gerente_cadastra_somente_funcao_operacional_na_propria_loja(monkeypatch):
    inseridos = preparar(monkeypatch)
    gerente = UsuarioAtual(id_auth=uuid4(), papel=Papel.GERENTE_LOJA, id_loja=ID_LOJA)

    service.criar_usuario(ConexaoFalsa(), AuthFalso(), gerente, novo(id_loja=None))

    assert inseridos[0]["id_loja"] == ID_LOJA


@pytest.mark.parametrize("cargo", ["gerente_loja", "admin"])
def test_gerente_nao_pode_criar_cargo_privilegiado(monkeypatch, cargo):
    inseridos = preparar(monkeypatch)
    gerente = UsuarioAtual(id_auth=uuid4(), papel=Papel.GERENTE_LOJA, id_loja=ID_LOJA)

    with pytest.raises(CargoNaoPermitido):
        service.criar_usuario(
            ConexaoFalsa(), AuthFalso(), gerente, novo(cargo=cargo, id_loja=None)
        )
    assert inseridos == []


def test_gerente_nao_pode_cadastrar_em_outra_loja(monkeypatch):
    preparar(monkeypatch)
    gerente = UsuarioAtual(id_auth=uuid4(), papel=Papel.GERENTE_LOJA, id_loja=ID_LOJA)

    with pytest.raises(SemPermissao):
        service.criar_usuario(
            ConexaoFalsa(), AuthFalso(), gerente, novo(id_loja=uuid4())
        )


def test_email_ja_cadastrado_nao_envia_convite(monkeypatch):
    preparar(monkeypatch, email_em_uso=True)
    auth = AuthFalso()
    admin = UsuarioAtual(id_auth=uuid4(), papel=Papel.ADMIN)

    with pytest.raises(EmailJaCadastrado):
        service.criar_usuario(ConexaoFalsa(), auth, admin, novo())
    assert auth.convidados == []


def test_email_existente_no_auth_desfaz_cadastro(monkeypatch):
    preparar(monkeypatch)
    conexao = ConexaoFalsa()
    admin = UsuarioAtual(id_auth=uuid4(), papel=Papel.ADMIN)

    with pytest.raises(EmailJaCadastrado):
        service.criar_usuario(conexao, AuthFalso(EmailJaNoAuth()), admin, novo())
    assert conexao.eventos == ["rollback"]


def test_falha_apos_convite_desfaz_banco_e_remove_usuario_auth(monkeypatch):
    preparar(monkeypatch, ligar=False)
    conexao, auth = ConexaoFalsa(), AuthFalso()
    admin = UsuarioAtual(id_auth=uuid4(), papel=Papel.ADMIN)

    with pytest.raises(UsuarioNaoEncontrado):
        service.criar_usuario(conexao, auth, admin, novo())
    assert conexao.eventos == ["rollback"]
    assert auth.apagados == [ID_AUTH]
