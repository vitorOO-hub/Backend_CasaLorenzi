"""Rotas do saldo e das movimentacoes: papel, escopo de loja e validacao, sem banco."""

from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.db import get_executar
from app.core.papeis import Papel
from app.main import criar_app
from app.painel_estoque import service
from tests.auth_util import SUPABASE_URL, ParDeChaves, provedor_para
from tests.conftest import DATABASE_URL_TESTE

LOJA_A, LOJA_B = uuid4(), uuid4()
BASE = "/api/v1/painel/estoque"

ESCOPO = {
    "papel": "gerente_loja",
    "id_loja": str(LOJA_A),
    "loja_nome": "Centro",
    "pode_escolher_loja": False,
    "somente_minhas": False,
}
OPCOES = {
    "lojas": [{"id_loja": str(LOJA_A), "nome": "Centro"}],
    "rede": [{"id_loja": str(LOJA_A), "nome": "Centro"}],
    "categorias": ["Camisas"],
    "situacoes": [{"codigo": "ok", "nome": "OK"}],
    "tipos": [{"codigo": "entrada", "nome": "Entrada"}],
    "pecas": [{"id_variacao": str(uuid4()), "sku": "CL-X", "nome": "Camisa · Branco, M"}],
    "motivos_entrada": ["Recebimento de fornecedor"],
    "motivos_saida": ["Avaria"],
    "escopo": ESCOPO,
}
SALDO = {
    "resumo": {
        "unidades": 10,
        "pecas": 2,
        "estoque_baixo": 1,
        "esgotadas": 0,
        "valor_em_estoque": 1500.5,
    },
    "lojas": [{"id_loja": str(LOJA_A), "nome": "Centro"}],
    "total": 1,
    "itens": [
        {
            "id_variacao": str(uuid4()),
            "sku": "CL-X",
            "produto": "Camisa",
            "cor": "Branco",
            "tamanho": "M",
            "categoria": "Camisas",
            "preco": 149.9,
            "total": 4,
            "minimo_total": 5,
            "situacao": "baixo",
            "por_loja": [{"id_loja": str(LOJA_A), "quantidade": 4, "minimo": 5}],
        }
    ],
}
MOVIMENTACOES = {
    "total": 1,
    "itens": [
        {
            "id_movimentacao": str(uuid4()),
            "data": "2026-10-07T12:00:00Z",
            "id_loja": str(LOJA_A),
            "loja_nome": "Centro",
            "id_variacao": str(uuid4()),
            "sku": "CL-X",
            "produto": "Camisa",
            "cor": "Branco",
            "tamanho": "M",
            "tipo_codigo": "venda",
            "tipo_nome": "Venda",
            "grupo": "saida",
            "quantidade": -2,
            "quantidade_anterior": 6,
            "quantidade_posterior": 4,
            "responsavel": None,
            "motivo": "Pedido SD-1",
            "numero_pedido": "SD-1",
        }
    ],
}
PERIODO_OK = {"de": "2026-09-01", "ate": "2026-09-30"}


@pytest.fixture
def chamadas(monkeypatch):
    registro = []

    def grava(nome, retorno):
        def falso(*args, **kwargs):
            registro.append((nome, args, kwargs))
            return retorno

        monkeypatch.setattr(service, nome, falso)

    grava("montar_opcoes", OPCOES)
    grava("montar_saldo", SALDO)
    grava("montar_movimentacoes", MOVIMENTACOES)
    monkeypatch.setattr(
        service, "filtro_de_movimentacoes", lambda conexao, usuario, **filtros: ("filtro", filtros)
    )
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


ROTAS = ["/opcoes", "/saldo", "/movimentacoes"]
PERMITIDOS = [Papel.OPERADOR_ESTOQUE, Papel.GERENTE_LOJA, Papel.ADMIN]


@pytest.mark.parametrize("rota", ROTAS)
def test_sem_token_e_401(cliente, rota):
    assert cliente.get(BASE + rota).status_code == 401


@pytest.mark.parametrize("rota", ROTAS)
@pytest.mark.parametrize("papel", [None, Papel.ATENDENTE], ids=["cliente", "atendente"])
def test_cliente_e_atendente_nao_entram(cliente, par, chamadas, rota, papel):
    resposta = cliente.get(BASE + rota, headers=token(par, papel))
    assert resposta.status_code == 403
    assert chamadas == []


@pytest.mark.parametrize("rota", ROTAS)
@pytest.mark.parametrize("papel", PERMITIDOS)
def test_equipe_de_estoque_gerente_e_admin_entram(cliente, par, rota, papel):
    assert cliente.get(BASE + rota, headers=token(par, papel)).status_code == 200


@pytest.mark.parametrize("rota", ROTAS)
@pytest.mark.parametrize("papel", [Papel.OPERADOR_ESTOQUE, Papel.GERENTE_LOJA])
def test_quem_e_de_loja_nao_consulta_outra(cliente, par, chamadas, rota, papel):
    params = {"id_loja": str(LOJA_B)}
    resposta = cliente.get(BASE + rota, params=params, headers=token(par, papel))
    assert resposta.status_code == 403
    assert chamadas == []


def test_o_filtro_de_loja_vem_sempre_do_token(cliente, par, chamadas):
    cabecalho = token(par, Papel.GERENTE_LOJA)
    cliente.get(BASE + "/saldo", headers=cabecalho)
    cliente.get(BASE + "/movimentacoes", headers=cabecalho)
    cliente.get(BASE + "/opcoes", headers=cabecalho)
    assert chamadas[0][1][1].id_loja == LOJA_A  # saldo
    assert chamadas[1][1][1][1]["id_loja"] == LOJA_A  # movimentacoes
    assert chamadas[2][1][2] == LOJA_A  # opcoes


def test_admin_ve_a_rede_ou_escolhe_a_loja(cliente, par, chamadas):
    cliente.get(BASE + "/saldo", headers=token(par, Papel.ADMIN))
    cliente.get(BASE + "/saldo", params={"id_loja": str(LOJA_B)}, headers=token(par, Papel.ADMIN))
    assert [c[1][1].id_loja for c in chamadas] == [None, LOJA_B]


def test_filtros_do_saldo_chegam_ao_servico(cliente, par, chamadas):
    params = {
        "busca": "linho",
        "categoria": "Camisas",
        "situacao": "baixo",
        "limit": 10,
        "offset": 20,
    }
    cliente.get(BASE + "/saldo", params=params, headers=token(par, Papel.GERENTE_LOJA))
    _, args, kwargs = chamadas[0]
    filtro = args[1]
    assert (filtro.busca, filtro.categoria, filtro.situacao) == ("linho", "Camisas", "baixo")
    assert (kwargs["limit"], kwargs["offset"]) == (10, 20)


def test_filtros_das_movimentacoes_chegam_ao_servico(cliente, par, chamadas):
    params = {"tipo": "ajuste", "sku": "CL-X", **PERIODO_OK, "limit": 5}
    cliente.get(BASE + "/movimentacoes", params=params, headers=token(par, Papel.ADMIN))
    _, args, kwargs = next(c for c in chamadas if c[0] == "montar_movimentacoes")
    assert args[1] == (
        "filtro",
        {
            "id_loja": None,
            "grupo": "ajuste",
            "sku": "CL-X",
            "de": date(2026, 9, 1),
            "ate": date(2026, 9, 30),
        },
    )
    assert kwargs["limit"] == 5


@pytest.mark.parametrize(
    ("rota", "params"),
    [
        ("/saldo", {"situacao": "quebrado"}),
        ("/saldo", {"situacao": "ok' OR 1=1"}),
        ("/saldo", {"busca": "x" * 81}),
        ("/saldo", {"limit": 0}),
        ("/saldo", {"limit": 201}),
        ("/saldo", {"offset": -1}),
        ("/movimentacoes", {"tipo": "venda"}),
        ("/movimentacoes", {"tipo": "entrada; DROP TABLE estoque"}),
        ("/movimentacoes", {"de": "ontem"}),
        ("/movimentacoes", {"limit": 101}),
        ("/movimentacoes", {"sku": "x" * 61}),
        ("/opcoes", {"id_loja": "nao-e-uuid"}),
    ],
)
def test_parametros_invalidos_sao_422(cliente, par, chamadas, rota, params):
    resposta = cliente.get(BASE + rota, params=params, headers=token(par, Papel.GERENTE_LOJA))
    assert resposta.status_code == 422
    assert chamadas == []


def test_a_resposta_segue_o_contrato(cliente, par):
    cabecalho = token(par, Papel.GERENTE_LOJA)
    assert cliente.get(BASE + "/saldo", headers=cabecalho).json() == SALDO
    assert cliente.get(BASE + "/opcoes", headers=cabecalho).json() == OPCOES
    assert cliente.get(BASE + "/movimentacoes", headers=cabecalho).json() == MOVIMENTACOES
