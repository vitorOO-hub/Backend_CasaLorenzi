"""Vigencia do token: a conta do JWT precisa continuar valendo no banco."""

from uuid import uuid4

import pytest

from app.core import vigencia
from app.core.erros_auth import NaoAutenticado
from app.core.papeis import Papel, UsuarioAtual


@pytest.fixture(autouse=True)
def _ligada(monkeypatch):
    monkeypatch.setattr(vigencia, "ATIVA", True)
    vigencia._conferidos.clear()
    yield
    vigencia._conferidos.clear()


class Banco:
    """Executor falso: devolve a linha da conta e conta quantas consultas foram feitas."""

    def __init__(self, linha):
        self.linha = linha
        self.consultas = 0

    def __call__(self, operacao):
        self.consultas += 1

        class Conexao:
            def execute(_, *_a, **_k):
                return type("R", (), {"first": lambda _s: self.linha})()

        return operacao(Conexao())


LOJA = uuid4()


def gerente():
    return UsuarioAtual(id_auth=uuid4(), papel=Papel.GERENTE_LOJA, id_loja=LOJA)


def test_conta_ativa_com_o_mesmo_cargo_e_loja_passa_e_usa_cache():
    banco = Banco(("gerente_loja", LOJA, True))
    usuario = gerente()
    vigencia.conferir(usuario, banco)
    vigencia.conferir(usuario, banco)
    assert banco.consultas == 1


@pytest.mark.parametrize(
    "linha",
    [
        None,  # a conta sumiu
        ("gerente_loja", LOJA, False),  # desativada
        ("atendente", LOJA, True),  # cargo mudou depois que o token foi emitido
        ("gerente_loja", uuid4(), True),  # trocou de loja
    ],
)
def test_conta_que_nao_vale_mais_responde_401(linha):
    with pytest.raises(NaoAutenticado):
        vigencia.conferir(gerente(), Banco(linha))


def test_admin_nao_depende_de_loja():
    admin = UsuarioAtual(id_auth=uuid4(), papel=Papel.ADMIN)
    vigencia.conferir(admin, Banco(("admin", None, True)))


def test_cache_expira_e_a_desativacao_vale_na_proxima_conferencia(monkeypatch):
    usuario = gerente()
    banco = Banco(("gerente_loja", LOJA, True))
    vigencia.conferir(usuario, banco)
    banco.linha = ("gerente_loja", LOJA, False)
    vigencia.conferir(usuario, banco)  # ainda dentro do cache
    vigencia.esquecer(usuario.id_auth)  # o admin acabou de mudar a conta
    with pytest.raises(NaoAutenticado):
        vigencia.conferir(usuario, banco)


def test_cliente_sem_papel_nao_passa_por_aqui():
    banco = Banco(None)
    vigencia.conferir(UsuarioAtual(id_auth=uuid4()), banco)
    assert banco.consultas == 0
