"""Rotas do n8n para o operador de estoque, sem banco: chave, limites dos parametros e o formato
da resposta. As consultas sao testadas contra o Postgres em tests/banco/test_automacoes_estoque.py.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.automacoes import service as automacoes
from tests.auth_util import ParDeChaves
from tests.automacoes.test_base_assistente import AUTOMACOES, CHAVE, montar_cliente

LOJA = uuid4()
COM_CHAVE = {"X-Chave-Automacao": CHAVE}
DO_DIA = {
    "gerado_em": datetime(2026, 10, 29, 11, tzinfo=UTC),
    "criterios": {"abaixo_do_minimo": "x", "transferencias": "y", "ajustes": "z"},
    "lojas_com_pendencias": 1,
    "lojas": [
        {
            "id_loja": LOJA,
            "loja": "Barra",
            "tem_pendencias": True,
            "abaixo_do_minimo": [
                {
                    "sku": "CL-1",
                    "produto": "Camisa",
                    "cor": "azul",
                    "tamanho": "M",
                    "saldo": 1,
                    "minimo": 3,
                    "lojas_com_sobra": [{"loja": "Savassi", "sobra": 4}],
                }
            ],
            "para_responder": [],
            "pedidos_sem_resposta": [],
            "a_receber": [],
            "ajustes_pendentes": [],
        }
    ],
}
PARADO = {"dias": 60, "criterio": "x", "lojas_com_estoque_parado": 0, "lojas": []}


@pytest.fixture
def chamadas(monkeypatch):
    registro = []

    def falso(nome, retorno):
        def chamar(conexao, **kwargs):
            registro.append((nome, kwargs))
            return retorno

        monkeypatch.setattr(automacoes, nome, chamar)

    falso("estoque_do_dia", DO_DIA)
    falso("estoque_parado_por_loja", PARADO)
    return registro


@pytest.fixture
def cliente(chamadas):
    return montar_cliente(ParDeChaves(), chave_automacao=CHAVE)


@pytest.mark.parametrize("rota", ["/estoque-do-dia", "/estoque-parado"])
def test_sem_chave_e_401(cliente, chamadas, rota):
    assert cliente.get(AUTOMACOES + rota).status_code == 401
    assert chamadas == []


def test_estoque_do_dia_usa_prazos_padrao(cliente, chamadas):
    resposta = cliente.get(AUTOMACOES + "/estoque-do-dia", headers=COM_CHAVE)

    assert resposta.status_code == 200
    assert chamadas == [("estoque_do_dia", {"horas": 24, "dias": 3})]
    [loja] = resposta.json()["lojas"]
    assert loja["abaixo_do_minimo"][0]["lojas_com_sobra"] == [{"loja": "Savassi", "sobra": 4}]


def test_estoque_do_dia_aceita_outros_prazos(cliente, chamadas):
    resposta = cliente.get(
        AUTOMACOES + "/estoque-do-dia?horas_sem_resposta=48&dias_em_transito=5", headers=COM_CHAVE
    )

    assert resposta.status_code == 200
    assert chamadas == [("estoque_do_dia", {"horas": 48, "dias": 5})]


@pytest.mark.parametrize(
    "consulta",
    [
        "/estoque-do-dia?horas_sem_resposta=0",
        "/estoque-do-dia?dias_em_transito=91",
        "/estoque-parado?dias=3",
        "/estoque-parado?limite=101",
    ],
)
def test_parametros_fora_do_limite_sao_recusados(cliente, chamadas, consulta):
    assert cliente.get(AUTOMACOES + consulta, headers=COM_CHAVE).status_code == 422
    assert chamadas == []


def test_estoque_parado_usa_padroes(cliente, chamadas):
    resposta = cliente.get(AUTOMACOES + "/estoque-parado", headers=COM_CHAVE)

    assert resposta.status_code == 200
    assert chamadas == [("estoque_parado_por_loja", {"dias": 60, "limite": 20})]


RELATORIOS = {
    "data": "2026-10-30",
    "semanal": True,
    "motivo_semanal": "x",
    "total": 0,
    "emails": [],
}


@pytest.fixture
def relatorios(monkeypatch):
    registro = []

    def chamar(conexao, **kwargs):
        registro.append(kwargs)
        return RELATORIOS

    monkeypatch.setattr(automacoes, "relatorios_estoque", chamar)
    return registro


def test_relatorios_usam_padroes_e_o_painel_do_front(cliente, relatorios):
    resposta = cliente.get(AUTOMACOES + "/relatorios-estoque", headers=COM_CHAVE)

    assert resposta.status_code == 200
    [chamada] = relatorios
    assert chamada["semanal"] == "auto" and chamada["limite"] == 30
    assert chamada["painel_url"].endswith("/painel/estoque")


def test_relatorios_aceitam_forcar_o_semanal(cliente, relatorios):
    resposta = cliente.get(AUTOMACOES + "/relatorios-estoque?semanal=sim", headers=COM_CHAVE)
    assert resposta.status_code == 200
    assert relatorios[0]["semanal"] == "sim"
    assert (
        cliente.get(
            AUTOMACOES + "/relatorios-estoque?semanal=talvez", headers=COM_CHAVE
        ).status_code
        == 422
    )


def test_relatorios_sem_chave_e_401(cliente, relatorios):
    assert cliente.get(AUTOMACOES + "/relatorios-estoque").status_code == 401
    assert relatorios == []
