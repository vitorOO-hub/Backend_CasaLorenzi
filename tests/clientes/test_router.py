"""Rotas de clientes do painel: papel, escopo, validacao e privacidade, sem banco."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.chamados import repositorio as repo_chamados
from app.clientes import repositorio as repo_clientes
from app.clientes import service
from app.clientes.erros import ClienteNaoEncontrado
from app.core.config import Settings
from app.core.db import get_executar
from app.core.papeis import Papel
from app.main import criar_app
from tests.auth_util import SUPABASE_URL, ParDeChaves, provedor_para
from tests.conftest import DATABASE_URL_TESTE

LOJA_A, LOJA_B = uuid4(), uuid4()
ID_USUARIO = uuid4()
ID = uuid4()
BASE = "/api/v1/painel/clientes"

ITEM = {
    "id_cliente": str(ID),
    "nome": "Helena",
    "email": "helena@exemplo.com",
    "telefone": "11 99999-0000",
    "cidade": "Sao Paulo, SP",
    "cliente_desde": "2025-01-10T00:00:00+00:00",
    "total_chamados": 2,
    "chamados_em_aberto": 1,
    "compras": None,
    "total_gasto": None,
}


@pytest.fixture
def chamadas(monkeypatch):
    registro = []
    monkeypatch.setattr(repo_chamados, "id_usuario_ativo", lambda _c, _a: ID_USUARIO)

    def lista_falsa(conexao, usuario, escopo, **filtros):
        registro.append(("listar", usuario, escopo, filtros))
        return {"total": 1, "itens": [ITEM]}

    monkeypatch.setattr(service, "listar", lista_falsa)

    def ficha_falsa(conexao, usuario, escopo, id_cliente):
        registro.append(("ficha", usuario, escopo, id_cliente))
        return {
            "cliente": {
                k: ITEM[k]
                for k in ("id_cliente", "nome", "email", "telefone", "cidade", "cliente_desde")
            },
            "resumo": {
                "chamados": 2,
                "chamados_em_aberto": 1,
                "compras": None,
                "total_gasto": None,
                "ticket_medio": None,
            },
            "chamados": [],
            "compras": None,
        }

    monkeypatch.setattr(service, "ficha", ficha_falsa)
    return registro


@pytest.fixture
def par():
    return ParDeChaves()


@pytest.fixture
def cliente(par, chamadas):
    app = criar_app(
        Settings(_env_file=None, database_url=DATABASE_URL_TESTE, supabase_url=SUPABASE_URL)
    )
    app.state.provedor_chaves = provedor_para(par)
    app.dependency_overrides[get_executar] = lambda: lambda operacao: operacao(None)
    return TestClient(app)


def token(par, papel, loja=LOJA_A):
    claims = {}
    if papel is not None:
        claims["papel"] = papel.value
        if papel is not Papel.ADMIN:
            claims["loja_id"] = str(loja)
    return {"Authorization": f"Bearer {par.emitir(**claims)}"}


ROTAS = ["", f"/{ID}"]


@pytest.mark.parametrize("caminho", ROTAS)
def test_sem_token_responde_401(cliente, caminho):
    assert cliente.get(BASE + caminho).status_code == 401


@pytest.mark.parametrize("caminho", ROTAS)
@pytest.mark.parametrize("papel", [None, Papel.OPERADOR_ESTOQUE])
def test_cliente_e_operador_de_estoque_nao_entram(cliente, par, caminho, papel):
    assert cliente.get(BASE + caminho, headers=token(par, papel)).status_code == 403


@pytest.mark.parametrize("caminho", ROTAS)
@pytest.mark.parametrize("papel", [Papel.ATENDENTE, Papel.GERENTE_LOJA, Papel.ADMIN])
def test_equipe_de_atendimento_entra(cliente, par, caminho, papel):
    assert cliente.get(BASE + caminho, headers=token(par, papel)).status_code == 200


@pytest.mark.parametrize("caminho", ROTAS)
@pytest.mark.parametrize("papel", [Papel.ATENDENTE, Papel.GERENTE_LOJA])
def test_atendente_e_gerente_nao_pedem_outra_loja(cliente, par, chamadas, caminho, papel):
    resposta = cliente.get(
        BASE + caminho, headers=token(par, papel), params={"id_loja": str(LOJA_B)}
    )
    assert resposta.status_code == 403
    assert chamadas == []


def test_escopo_da_equipe_e_a_loja_do_token_mais_os_sem_loja(cliente, par, chamadas):
    cliente.get(BASE, headers=token(par, Papel.ATENDENTE))
    escopo = chamadas[0][2]
    assert (escopo.id_loja, escopo.incluir_sem_loja, escopo.id_usuario) == (
        LOJA_A,
        True,
        ID_USUARIO,
    )


def test_admin_ve_a_rede_ou_filtra_uma_loja(cliente, par, chamadas):
    cliente.get(BASE, headers=token(par, Papel.ADMIN))
    cliente.get(BASE, headers=token(par, Papel.ADMIN), params={"id_loja": str(LOJA_B)})
    assert chamadas[0][2].id_loja is None and chamadas[1][2].id_loja == LOJA_B


def test_conta_sem_cadastro_ativo_leva_403(cliente, par, monkeypatch):
    monkeypatch.setattr(repo_chamados, "id_usuario_ativo", lambda _c, _a: None)
    assert cliente.get(BASE, headers=token(par, Papel.ATENDENTE)).status_code == 403


def test_repassa_busca_secao_e_paginacao(cliente, par, chamadas):
    cliente.get(
        BASE,
        headers=token(par, Papel.GERENTE_LOJA),
        params={"busca": "  helena  ", "secao": "com_aberto", "limit": 50, "offset": 10},
    )
    assert chamadas[0][3] == {
        "busca": "  helena  ",
        "secao": "com_aberto",
        "limit": 50,
        "offset": 10,
    }


def test_padroes_da_lista(cliente, par, chamadas):
    cliente.get(BASE, headers=token(par, Papel.ATENDENTE))
    assert chamadas[0][3] == {"busca": None, "secao": "todos", "limit": 20, "offset": 0}


@pytest.mark.parametrize(
    "params",
    [
        {"secao": "outra"},
        {"busca": "a" * 81},
        {"id_loja": "nao-e-uuid"},
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
    ],
)
def test_parametros_invalidos_respondem_422(cliente, par, params):
    assert cliente.get(BASE, headers=token(par, Papel.ADMIN), params=params).status_code == 422


def test_id_que_nao_e_uuid_responde_422(cliente, par):
    assert cliente.get(f"{BASE}/abc", headers=token(par, Papel.ADMIN)).status_code == 422


def test_cliente_fora_do_escopo_responde_404_em_portugues(cliente, par, monkeypatch):
    def falha(*_a, **_k):
        raise ClienteNaoEncontrado()

    monkeypatch.setattr(service, "ficha", falha)
    resposta = cliente.get(f"{BASE}/{ID}", headers=token(par, Papel.ATENDENTE))
    assert resposta.status_code == 404
    assert resposta.json() == {"detail": "Cliente nao encontrado"}


def test_resposta_nao_traz_documento_nem_campo_extra(cliente, par, chamadas, monkeypatch):
    monkeypatch.setattr(
        service,
        "listar",
        lambda *a, **k: {"total": 1, "itens": [{**ITEM, "documento": "123.456.789-00"}]},
    )
    # extra="forbid" nas saidas: campo nao combinado (como o CPF) e recusado pelo servidor
    # em vez de ser devolvido. Em producao isso vira 500 generico, sem o dado.
    sem_levantar = TestClient(cliente.app, raise_server_exceptions=False)
    resposta = sem_levantar.get(BASE, headers=token(par, Papel.ADMIN))
    assert resposta.status_code == 500
    assert "123.456.789-00" not in resposta.text


def test_rotas_estao_sob_api_v1(cliente):
    caminhos = set(cliente.get("/openapi.json").json()["paths"])
    assert {BASE, f"{BASE}/{{id_cliente}}"} <= caminhos


class TestRegrasPuras:
    def test_so_gerente_e_admin_veem_compras(self):
        from app.core.papeis import UsuarioAtual

        def quem(papel, loja=None):
            return UsuarioAtual(id_auth=uuid4(), papel=papel, id_loja=loja)

        assert service.pode_ver_compras(quem(Papel.ATENDENTE, LOJA_A)) is False
        assert service.pode_ver_compras(quem(Papel.GERENTE_LOJA, LOJA_A)) is True
        assert service.pode_ver_compras(quem(Papel.ADMIN)) is True

    @pytest.mark.parametrize(
        ("digitado", "esperado"),
        [
            (None, None),
            ("", None),
            ("   ", None),
            ("helena", "%helena%"),
            ("  helena ", "%helena%"),
            ("100%", "%100\\%%"),
            ("a_b", "%a\\_b%"),
            ("a\\b", "%a\\\\b%"),
        ],
    )
    def test_busca_trata_coringas_como_letras(self, digitado, esperado):
        assert repo_clientes.escapar_busca(digitado) == esperado
