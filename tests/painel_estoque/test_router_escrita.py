"""Rotas de escrita do estoque: papel, corpo aceito e o que chega ao servico, sem banco."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.db import get_executar
from app.core.papeis import Papel
from app.main import criar_app
from app.painel_estoque import service_escrita
from tests.auth_util import SUPABASE_URL, ParDeChaves, provedor_para
from tests.conftest import DATABASE_URL_TESTE

LOJA_A, LOJA_B = uuid4(), uuid4()
ID_AJUSTE = uuid4()
BASE = "/api/v1/painel/estoque"

MOVIMENTACAO = {
    "id_movimentacao": str(uuid4()),
    "data": "2026-10-07T12:00:00Z",
    "id_loja": str(LOJA_A),
    "loja_nome": "Centro",
    "id_variacao": str(uuid4()),
    "sku": "CL-X",
    "produto": "Camisa",
    "cor": "Branco",
    "tamanho": "M",
    "tipo_codigo": "entrada",
    "tipo_nome": "Entrada",
    "grupo": "entrada",
    "quantidade": 5,
    "quantidade_anterior": 1,
    "quantidade_posterior": 6,
    "responsavel": "Ana",
    "motivo": "Recebimento de fornecedor",
    "numero_pedido": None,
}
AJUSTE = {
    "id_ajuste": str(ID_AJUSTE),
    "id_loja": str(LOJA_A),
    "loja_nome": "Centro",
    "id_variacao": str(uuid4()),
    "sku": "CL-X",
    "produto": "Camisa",
    "cor": "Branco",
    "tamanho": "M",
    "quantidade": -2,
    "saldo_atual": 6,
    "motivo": "Contagem",
    "status": "pendente",
    "motivo_recusa": None,
    "solicitante": "Ana",
    "decisor": None,
    "solicitado_em": "2026-10-07T12:00:00Z",
    "decidido_em": None,
}
LISTA = {"total": 1, "pendentes": 1, "itens": [AJUSTE]}
MOVIMENTO_OK = {
    "sku": "CL-X",
    "tipo": "entrada",
    "quantidade": 5,
    "motivo": "Recebimento de fornecedor",
}
AJUSTE_OK = {"sku": "CL-X", "quantidade_contada": 4, "motivo": "Contagem do inventario"}


@pytest.fixture
def chamadas(monkeypatch):
    registro = []

    def grava(nome, retorno):
        def falso(*args, **kwargs):
            registro.append((nome, args, kwargs))
            return retorno

        monkeypatch.setattr(service_escrita, nome, falso)

    grava("registrar_movimentacao", MOVIMENTACAO)
    grava("solicitar_ajuste", AJUSTE)
    grava("listar_ajustes", LISTA)
    grava("aprovar_ajuste", {**AJUSTE, "status": "aprovado"})
    grava("recusar_ajuste", {**AJUSTE, "status": "rejeitado", "motivo_recusa": "Nao bate"})
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


ESCRITAS = [
    ("POST", "/movimentacoes", MOVIMENTO_OK),
    ("POST", "/ajustes", AJUSTE_OK),
    ("POST", f"/ajustes/{ID_AJUSTE}/aprovar", None),
    ("POST", f"/ajustes/{ID_AJUSTE}/recusar", {"motivo": "Nao bate com a nota"}),
]
TODAS = [*ESCRITAS, ("GET", "/ajustes", None)]


def chamar(cliente, metodo, rota, corpo, cabecalho, **params):
    return cliente.request(metodo, BASE + rota, json=corpo, headers=cabecalho, params=params)


@pytest.mark.parametrize(("metodo", "rota", "corpo"), TODAS)
def test_sem_token_e_401(cliente, metodo, rota, corpo):
    assert chamar(cliente, metodo, rota, corpo, None).status_code == 401


@pytest.mark.parametrize(("metodo", "rota", "corpo"), TODAS)
@pytest.mark.parametrize("papel", [None, Papel.ATENDENTE], ids=["cliente", "atendente"])
def test_cliente_e_atendente_nao_mexem_no_estoque(
    cliente, par, chamadas, metodo, rota, corpo, papel
):
    resposta = chamar(cliente, metodo, rota, corpo, token(par, papel))
    assert resposta.status_code == 403
    assert chamadas == []


@pytest.mark.parametrize("papel", [Papel.OPERADOR_ESTOQUE, Papel.GERENTE_LOJA, Papel.ADMIN])
def test_equipe_registra_movimentacao_e_pede_ajuste(cliente, par, papel):
    cabecalho = token(par, papel)
    r = chamar(cliente, "POST", "/movimentacoes", MOVIMENTO_OK, cabecalho)
    assert r.status_code == 201 and r.json() == MOVIMENTACAO
    r = chamar(cliente, "POST", "/ajustes", AJUSTE_OK, cabecalho)
    assert r.status_code == 201 and r.json() == AJUSTE
    assert chamar(cliente, "GET", "/ajustes", None, cabecalho).json() == LISTA


@pytest.mark.parametrize("rota", [f"/ajustes/{ID_AJUSTE}/aprovar", f"/ajustes/{ID_AJUSTE}/recusar"])
def test_operador_nao_decide_ajuste(cliente, par, chamadas, rota):
    corpo = {"motivo": "Nao bate com a nota"}
    r = chamar(cliente, "POST", rota, corpo, token(par, Papel.OPERADOR_ESTOQUE))
    assert r.status_code == 403
    assert chamadas == []


@pytest.mark.parametrize("papel", [Papel.GERENTE_LOJA, Papel.ADMIN])
def test_gerente_e_admin_decidem(cliente, par, papel):
    cabecalho = token(par, papel)
    r = chamar(cliente, "POST", f"/ajustes/{ID_AJUSTE}/aprovar", None, cabecalho)
    assert r.status_code == 200 and r.json()["status"] == "aprovado"
    r = chamar(cliente, "POST", f"/ajustes/{ID_AJUSTE}/recusar", {"motivo": "Nao bate"}, cabecalho)
    assert r.status_code == 200 and r.json()["motivo_recusa"] == "Nao bate"


def test_quem_opera_e_o_token_e_a_loja_do_corpo_vai_ao_servico(cliente, par, chamadas):
    corpo = {**MOVIMENTO_OK, "id_loja": str(LOJA_B)}
    chamar(cliente, "POST", "/movimentacoes", corpo, token(par, Papel.ADMIN))
    _, args, kwargs = chamadas[0]
    assert args[1].papel is Papel.ADMIN and args[1].id_loja is None
    assert kwargs == {
        "id_loja": LOJA_B,
        "sku": "CL-X",
        "tipo": "entrada",
        "quantidade": 5,
        "motivo": "Recebimento de fornecedor",
    }


def test_espacos_do_motivo_e_do_sku_sao_aparados(cliente, par, chamadas):
    corpo = {**MOVIMENTO_OK, "sku": "  CL-X ", "motivo": "  Avaria  ", "tipo": "saida"}
    chamar(cliente, "POST", "/movimentacoes", corpo, token(par, Papel.GERENTE_LOJA))
    kwargs = chamadas[0][2]
    assert (kwargs["sku"], kwargs["motivo"], kwargs["tipo"]) == ("CL-X", "Avaria", "saida")


@pytest.mark.parametrize(
    "extra",
    [
        {"id_usuario": str(uuid4())},
        {"responsavel": "Outra pessoa"},
        {"id_usuario_responsavel": str(uuid4())},
        {"status": "aprovado"},
        {"quantidade_posterior": 999},
    ],
)
def test_identidade_e_saldo_nunca_vem_do_corpo(cliente, par, chamadas, extra):
    for rota, base in (("/movimentacoes", MOVIMENTO_OK), ("/ajustes", AJUSTE_OK)):
        r = chamar(cliente, "POST", rota, {**base, **extra}, token(par, Papel.GERENTE_LOJA))
        assert r.status_code == 422
    assert chamadas == []


@pytest.mark.parametrize(
    "alteracao",
    [
        {"tipo": "venda"},
        {"tipo": "ajuste_negativo"},
        {"tipo": "ENTRADA"},
        {"quantidade": 0},
        {"quantidade": -3},
        {"quantidade": 100_001},
        {"quantidade": 1.5},
        {"quantidade": "5"},
        {"quantidade": None},
        {"motivo": "ab"},
        {"motivo": "   "},
        {"motivo": "x" * 201},
        {"sku": ""},
        {"sku": "x" * 61},
        {"id_loja": "nao-e-uuid"},
    ],
)
def test_corpo_invalido_da_movimentacao_e_422(cliente, par, chamadas, alteracao):
    r = chamar(
        cliente, "POST", "/movimentacoes", {**MOVIMENTO_OK, **alteracao}, token(par, Papel.ADMIN)
    )
    assert r.status_code == 422
    assert chamadas == []


@pytest.mark.parametrize(
    "alteracao",
    [
        {"quantidade_contada": -1},
        {"quantidade_contada": 100_001},
        {"quantidade_contada": "4"},
        {"motivo": "ab"},
        {"motivo": "x" * 301},
        {"sku": ""},
    ],
)
def test_corpo_invalido_do_ajuste_e_422(cliente, par, chamadas, alteracao):
    r = chamar(cliente, "POST", "/ajustes", {**AJUSTE_OK, **alteracao}, token(par, Papel.ADMIN))
    assert r.status_code == 422
    assert chamadas == []


@pytest.mark.parametrize(
    "corpo", [{}, {"motivo": "ab"}, {"motivo": "x" * 301}, {"motivo": "ok ok", "extra": 1}]
)
def test_recusa_exige_motivo_valido(cliente, par, chamadas, corpo):
    r = chamar(
        cliente, "POST", f"/ajustes/{ID_AJUSTE}/recusar", corpo, token(par, Papel.GERENTE_LOJA)
    )
    assert r.status_code == 422
    assert chamadas == []


def test_id_do_ajuste_precisa_ser_uuid(cliente, par):
    r = chamar(cliente, "POST", "/ajustes/abc/aprovar", None, token(par, Papel.GERENTE_LOJA))
    assert r.status_code == 422


@pytest.mark.parametrize("situacao", ["pendente", "aprovado", "rejeitado", "decididos"])
def test_filtro_de_situacao_dos_ajustes(cliente, par, chamadas, situacao):
    chamar(cliente, "GET", "/ajustes", None, token(par, Papel.GERENTE_LOJA), situacao=situacao)
    assert chamadas[0][2]["status"] == situacao


@pytest.mark.parametrize(
    "params", [{"situacao": "todos"}, {"situacao": "x' OR 1=1"}, {"limit": 0}, {"limit": 101}]
)
def test_filtros_invalidos_dos_ajustes_sao_422(cliente, par, chamadas, params):
    r = chamar(cliente, "GET", "/ajustes", None, token(par, Papel.GERENTE_LOJA), **params)
    assert r.status_code == 422
    assert chamadas == []
