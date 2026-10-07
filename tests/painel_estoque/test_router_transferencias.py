"""Rotas de transferencias e estoque minimo: quem entra e quais corpos sao aceitos, sem banco."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.db import get_executar
from app.core.papeis import Papel
from app.main import criar_app
from app.painel_estoque import minimos, transferencias
from tests.auth_util import SUPABASE_URL, ParDeChaves, provedor_para
from tests.conftest import DATABASE_URL_TESTE

LOJA_A, LOJA_B = uuid4(), uuid4()
ID = uuid4()
BASE = "/api/v1/painel/estoque"
ITEM = {
    "id_transferencia": str(ID),
    "tipo": "transferencia",
    "status": "solicitada",
    "solicitada_em": "2026-10-07T12:00:00Z",
    "aceita_em": None,
    "recebida_em": None,
    "id_loja_origem": str(LOJA_A),
    "origem_nome": "Centro",
    "id_loja_destino": str(LOJA_B),
    "destino_nome": "Barra",
    "sku": "CL-X",
    "produto": "Camisa",
    "cor": "Branco",
    "tamanho": "M",
    "quantidade": 3,
    "observacao": None,
    "motivo_recusa": None,
    "solicitante": "Ana",
    "responsavel": None,
    "acoes": ["aceitar", "recusar"],
}
LISTA = {"total": 1, "aguardando_voce": 1, "itens": [ITEM]}
MINIMOS = {
    "id_loja": str(LOJA_A),
    "loja_nome": "Centro",
    "total": 0,
    "itens": [],
}
NOVA = {"sku": "CL-X", "quantidade": 3, "id_loja_origem": str(LOJA_A)}


@pytest.fixture
def chamadas(monkeypatch):
    registro = []

    def grava(modulo, nome, retorno):
        def falso(*args, **kwargs):
            registro.append((nome, args, kwargs))
            return retorno

        monkeypatch.setattr(modulo, nome, falso)

    for nome in ("solicitar", "pedir_reposicao", "aceitar", "recusar", "receber"):
        grava(transferencias, nome, ITEM)
    grava(transferencias, "listar_do_usuario", LISTA)
    grava(minimos, "listar", MINIMOS)
    grava(minimos, "definir", {"atualizados": 1})
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


def chamar(cliente, metodo, rota, corpo, cabecalho, **params):
    return cliente.request(metodo, BASE + rota, json=corpo, headers=cabecalho, params=params)


TRANSFERENCIAS = [
    ("GET", "/transferencias", None),
    ("POST", "/transferencias", NOVA),
    ("POST", "/transferencias/reposicoes", {"sku": "CL-X", "quantidade": 2}),
    ("POST", f"/transferencias/{ID}/aceitar", None),
    ("POST", f"/transferencias/{ID}/recusar", {"motivo": "Sem peca"}),
    ("POST", f"/transferencias/{ID}/receber", None),
]
MINIMOS_ROTAS = [
    ("GET", "/minimos", None),
    ("PUT", "/minimos", {"itens": [{"sku": "CL-X", "minimo": 3}]}),
]


@pytest.mark.parametrize(("metodo", "rota", "corpo"), [*TRANSFERENCIAS, *MINIMOS_ROTAS])
def test_sem_token_401_e_cliente_ou_atendente_403(cliente, par, chamadas, metodo, rota, corpo):
    assert chamar(cliente, metodo, rota, corpo, None).status_code == 401
    for papel in (None, Papel.ATENDENTE):
        assert chamar(cliente, metodo, rota, corpo, token(par, papel)).status_code == 403
    assert chamadas == []


@pytest.mark.parametrize(("metodo", "rota", "corpo"), TRANSFERENCIAS)
@pytest.mark.parametrize("papel", [Papel.OPERADOR_ESTOQUE, Papel.GERENTE_LOJA, Papel.ADMIN])
def test_equipe_de_estoque_opera_transferencias(cliente, par, metodo, rota, corpo, papel):
    resposta = chamar(cliente, metodo, rota, corpo, token(par, papel))
    assert resposta.status_code in (200, 201)


@pytest.mark.parametrize(("metodo", "rota", "corpo"), MINIMOS_ROTAS)
def test_estoque_minimo_e_so_da_gestao(cliente, par, chamadas, metodo, rota, corpo):
    assert (
        chamar(cliente, metodo, rota, corpo, token(par, Papel.OPERADOR_ESTOQUE)).status_code == 403
    )
    assert chamadas == []
    for papel in (Papel.GERENTE_LOJA, Papel.ADMIN):
        assert chamar(cliente, metodo, rota, corpo, token(par, papel)).status_code == 200


@pytest.mark.parametrize(
    "alteracao",
    [
        {"quantidade": 0},
        {"quantidade": "3"},
        {"quantidade": 100_001},
        {"sku": ""},
        {"id_loja_origem": "x"},
        {"observacao": "x" * 301},
        {"id_usuario_solicitante": str(uuid4())},
        {"status": "recebida"},
    ],
)
def test_pedido_de_transferencia_recusa_corpo_invalido(cliente, par, chamadas, alteracao):
    r = chamar(
        cliente, "POST", "/transferencias", {**NOVA, **alteracao}, token(par, Papel.GERENTE_LOJA)
    )
    assert r.status_code == 422
    assert chamadas == []


def test_pedido_sem_origem_e_422(cliente, par):
    corpo = {"sku": "CL-X", "quantidade": 1}
    assert (
        chamar(
            cliente, "POST", "/transferencias", corpo, token(par, Papel.GERENTE_LOJA)
        ).status_code
        == 422
    )


@pytest.mark.parametrize("corpo", [{"motivo": "x" * 301}, {"extra": 1}, {"status": "recebida"}])
def test_decisao_recusa_corpo_invalido(cliente, par, chamadas, corpo):
    for acao in ("aceitar", "recusar"):
        r = chamar(
            cliente, "POST", f"/transferencias/{ID}/{acao}", corpo, token(par, Papel.GERENTE_LOJA)
        )
        assert r.status_code == 422
    assert chamadas == []


@pytest.mark.parametrize(
    "params",
    [
        {"situacao": "todos"},
        {"situacao": "x' OR 1=1"},
        {"tipo": "venda"},
        {"limit": 101},
        {"id_loja": "x"},
    ],
)
def test_filtros_invalidos_da_lista(cliente, par, chamadas, params):
    r = chamar(cliente, "GET", "/transferencias", None, token(par, Papel.GERENTE_LOJA), **params)
    assert r.status_code == 422
    assert chamadas == []


def test_id_da_transferencia_precisa_ser_uuid(cliente, par):
    r = chamar(cliente, "POST", "/transferencias/abc/aceitar", None, token(par, Papel.GERENTE_LOJA))
    assert r.status_code == 422


@pytest.mark.parametrize(
    "corpo",
    [
        {"itens": []},
        {"itens": [{"sku": "A", "minimo": -1}]},
        {"itens": [{"sku": "A", "minimo": "3"}]},
        {"itens": [{"sku": "A", "minimo": 100_001}]},
        {"itens": [{"sku": "A", "minimo": 1}, {"sku": "A", "minimo": 2}]},
        {"itens": [{"sku": f"S{n}", "minimo": 1} for n in range(201)]},
        {"itens": [{"sku": "A", "minimo": 1, "saldo": 9}]},
        {"itens": [{"sku": "A", "minimo": 1}], "id_loja": "x"},
    ],
)
def test_minimos_recusam_corpo_invalido(cliente, par, chamadas, corpo):
    r = chamar(cliente, "PUT", "/minimos", corpo, token(par, Papel.GERENTE_LOJA))
    assert r.status_code == 422
    assert chamadas == []


def test_quem_age_e_o_token_e_a_loja_do_corpo_so_vai_ao_servico(cliente, par, chamadas):
    chamar(
        cliente,
        "POST",
        "/transferencias",
        {**NOVA, "id_loja": str(LOJA_B)},
        token(par, Papel.ADMIN),
    )
    _, args, _ = chamadas[0]
    assert args[1].papel is Papel.ADMIN and args[2].id_loja == LOJA_B
