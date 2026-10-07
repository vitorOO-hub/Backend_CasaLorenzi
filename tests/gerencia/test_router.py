"""Rotas do inicio do gerente: papel, escopo de loja e validacao, sem banco."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.db import get_executar
from app.core.papeis import Papel
from app.gerencia import service
from app.main import criar_app
from tests.auth_util import SUPABASE_URL, ParDeChaves, provedor_para
from tests.conftest import DATABASE_URL_TESTE

LOJA_A, LOJA_B = uuid4(), uuid4()
BASE = "/api/v1/painel/gerencia"
PERIODO = {"inicio": "2026-09-01", "fim": "2026-09-30"}

RESUMO = {
    "faturamento": 1000.0,
    "pedidos": 4,
    "pecas": 6,
    "ticket_medio": 250.0,
    "faturamento_online": 400.0,
    "pedidos_online": 2,
    "participacao_online": 0.4,
}
DASHBOARD = {
    "periodo": {"inicio": "2026-09-01", "fim": "2026-09-30"},
    "periodo_anterior": {"inicio": "2026-08-02", "fim": "2026-08-31"},
    "atual": RESUMO,
    "anterior": RESUMO,
    "serie_diaria": [{"data": "2026-09-01", "faturamento": 10.0, "pedidos": 1, "pecas": 1}],
    "movimento_semana": [{"dia_semana": 0, "pedidos": 3, "dias": 4, "pedidos_por_dia": 0.75}],
    "pecas_mais_vendidas": [
        {
            "id_produto": str(uuid4()),
            "nome": "Camisa",
            "categoria": "Camisas",
            "unidades": 3,
            "faturamento": 300.0,
        }
    ],
    "opcoes": {
        "lojas": [{"id_loja": str(LOJA_A), "nome": "Centro"}],
        "canais": [{"codigo": "loja", "nome": "Loja"}],
        "categorias": ["Camisas"],
    },
    "escopo": {
        "papel": "gerente_loja",
        "id_loja": str(LOJA_A),
        "loja_nome": "Centro",
        "pode_escolher_loja": False,
    },
}
REPOSICAO = {
    "total": 1,
    "itens": [
        {
            "id_variacao": str(uuid4()),
            "sku": "CL-CAM-LIN-BR-P",
            "produto": "Camisa",
            "cor": "Branco",
            "tamanho": "P",
            "categoria": "Camisas",
            "saldo": 0,
            "minimo": 3,
            "giro_diario": 0.5,
            "dias_cobertura": None,
            "situacao": "esgotada",
        }
    ],
}
PENDENCIAS = {
    "ajustes_para_aprovar": 1,
    "transferencias_aguardando": 2,
    "chamados_sem_resposta": 3,
    "total": 6,
}


@pytest.fixture
def chamadas(monkeypatch):
    registro = []

    def grava(nome, retorno):
        def falso(*args, **kwargs):
            registro.append((nome, args, kwargs))
            return retorno

        monkeypatch.setattr(service, nome, falso)

    grava("montar_dashboard", DASHBOARD)
    grava("montar_reposicao", REPOSICAO)
    grava("montar_pendencias", PENDENCIAS)
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


ROTAS = [("/dashboard", PERIODO), ("/reposicao", {}), ("/pendencias", {})]


@pytest.mark.parametrize(("rota", "params"), ROTAS)
def test_sem_token_e_401(cliente, rota, params):
    assert cliente.get(BASE + rota, params=params).status_code == 401


@pytest.mark.parametrize(("rota", "params"), ROTAS)
@pytest.mark.parametrize(
    "papel",
    [None, Papel.ATENDENTE, Papel.OPERADOR_ESTOQUE],
    ids=["cliente", "atendente", "operador"],
)
def test_so_gerente_e_admin_entram(cliente, par, chamadas, rota, params, papel):
    resposta = cliente.get(BASE + rota, params=params, headers=token(par, papel))
    assert resposta.status_code == 403
    assert chamadas == []


@pytest.mark.parametrize(("rota", "params"), ROTAS)
@pytest.mark.parametrize("papel", [Papel.GERENTE_LOJA, Papel.ADMIN])
def test_gerente_e_admin_recebem_200(cliente, par, rota, params, papel):
    assert cliente.get(BASE + rota, params=params, headers=token(par, papel)).status_code == 200


def test_o_gerente_sempre_consulta_a_propria_loja(cliente, par, chamadas):
    cliente.get(BASE + "/dashboard", params=PERIODO, headers=token(par, Papel.GERENTE_LOJA))
    cliente.get(BASE + "/reposicao", headers=token(par, Papel.GERENTE_LOJA))
    cliente.get(BASE + "/pendencias", headers=token(par, Papel.GERENTE_LOJA))
    lojas = [kwargs["filtro"].id_loja for _, _, kwargs in chamadas[:1]]
    lojas += [args[1].id_loja for _, args, _ in chamadas[1:]]
    assert lojas == [LOJA_A, LOJA_A, LOJA_A]


@pytest.mark.parametrize("rota", ["/dashboard", "/reposicao", "/pendencias"])
def test_gerente_nao_consulta_outra_loja(cliente, par, chamadas, rota):
    params = {**PERIODO, "id_loja": str(LOJA_B)}
    resposta = cliente.get(BASE + rota, params=params, headers=token(par, Papel.GERENTE_LOJA))
    assert resposta.status_code == 403
    assert chamadas == []


def test_gerente_pode_repetir_a_propria_loja(cliente, par):
    params = {**PERIODO, "id_loja": str(LOJA_A)}
    resposta = cliente.get(
        BASE + "/dashboard", params=params, headers=token(par, Papel.GERENTE_LOJA)
    )
    assert resposta.status_code == 200


def test_admin_ve_a_rede_ou_escolhe_a_loja(cliente, par, chamadas):
    cliente.get(BASE + "/dashboard", params=PERIODO, headers=token(par, Papel.ADMIN))
    cliente.get(
        BASE + "/dashboard",
        params={**PERIODO, "id_loja": str(LOJA_B)},
        headers=token(par, Papel.ADMIN),
    )
    assert [kwargs["filtro"].id_loja for _, _, kwargs in chamadas] == [None, LOJA_B]


def test_filtros_de_categoria_e_canal_chegam_ao_servico(cliente, par, chamadas):
    params = {**PERIODO, "categoria": "Camisas", "canal": "online"}
    cliente.get(BASE + "/dashboard", params=params, headers=token(par, Papel.GERENTE_LOJA))
    filtro = chamadas[0][2]["filtro"]
    assert (filtro.categoria, filtro.canal) == ("Camisas", "online")


def test_token_de_gerente_sem_loja_e_recusado(cliente, par):
    sem_loja = {"Authorization": f"Bearer {par.emitir(papel=Papel.GERENTE_LOJA.value)}"}
    assert cliente.get(BASE + "/dashboard", params=PERIODO, headers=sem_loja).status_code == 401


@pytest.mark.parametrize(
    "params",
    [
        {"inicio": "2026-09-30", "fim": "2026-09-01"},
        {"inicio": "2025-01-01", "fim": "2026-09-30"},
    ],
    ids=["fim antes do inicio", "periodo longo demais"],
)
def test_periodo_invalido_e_422(cliente, par, chamadas, params):
    resposta = cliente.get(
        BASE + "/dashboard", params=params, headers=token(par, Papel.GERENTE_LOJA)
    )
    assert resposta.status_code == 422
    assert chamadas == []


@pytest.mark.parametrize(
    "params",
    [
        {**PERIODO, "inicio": "ontem"},
        {**PERIODO, "canal": "telefone"},
        {**PERIODO, "canal": "online' OR 1=1"},
        {**PERIODO, "id_loja": "nao-e-uuid"},
        {**PERIODO, "categoria": "x" * 81},
    ],
)
def test_parametros_fora_do_formato_sao_422(cliente, par, chamadas, params):
    resposta = cliente.get(
        BASE + "/dashboard", params=params, headers=token(par, Papel.GERENTE_LOJA)
    )
    assert resposta.status_code == 422
    assert chamadas == []


def test_periodo_e_obrigatorio(cliente, par):
    resposta = cliente.get(BASE + "/dashboard", headers=token(par, Papel.GERENTE_LOJA))
    assert resposta.status_code == 422


@pytest.mark.parametrize("limite", [0, 51, -1])
def test_limite_da_reposicao_tem_teto(cliente, par, limite):
    resposta = cliente.get(
        BASE + "/reposicao", params={"limit": limite}, headers=token(par, Papel.GERENTE_LOJA)
    )
    assert resposta.status_code == 422


def test_pendencias_do_gerente_incluem_chamados_sem_loja_e_as_do_admin_nao_precisam(
    cliente, par, chamadas
):
    cliente.get(BASE + "/pendencias", headers=token(par, Papel.GERENTE_LOJA))
    cliente.get(BASE + "/pendencias", headers=token(par, Papel.ADMIN))
    assert [kwargs["incluir_chamados_sem_loja"] for _, _, kwargs in chamadas] == [True, False]


def test_a_resposta_segue_o_contrato(cliente, par):
    corpo = cliente.get(
        BASE + "/dashboard", params=PERIODO, headers=token(par, Papel.GERENTE_LOJA)
    ).json()
    assert set(corpo) == set(DASHBOARD)
    assert corpo["atual"]["ticket_medio"] == 250.0
    assert cliente.get(BASE + "/pendencias", headers=token(par, Papel.ADMIN)).json() == PENDENCIAS
    reposicao = cliente.get(BASE + "/reposicao", headers=token(par, Papel.ADMIN)).json()
    assert reposicao["itens"][0]["situacao"] == "esgotada"
