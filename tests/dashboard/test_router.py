"""Rotas do dashboard: autenticacao, papel, escopo de loja e validacao, sem banco."""

from datetime import date, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.db import get_executar
from app.core.papeis import Papel
from app.dashboard import service
from app.dashboard.erros import PeriodoInvalido, PeriodoLongoDemais
from app.main import criar_app
from tests.auth_util import SUPABASE_URL, ParDeChaves, provedor_para
from tests.conftest import DATABASE_URL_TESTE

LOJA_A, LOJA_B = uuid4(), uuid4()
PERIODO = {"inicio": "2026-10-01", "fim": "2026-10-07"}
RESUMO_VAZIO = {"total": 0, "resolvidos": 0, "taxa_resolucao": 0.0, "resposta_media_horas": None}

DASHBOARD_VAZIO = {
    "periodo": {"inicio": "2026-10-01", "fim": "2026-10-07"},
    "periodo_anterior": {"inicio": "2026-09-24", "fim": "2026-09-30"},
    "atual": RESUMO_VAZIO,
    "anterior": RESUMO_VAZIO,
    "volume_diario": [],
    "por_categoria": [],
    "resposta_por_canal": [],
    "opcoes": {"lojas": [], "canais": [], "categorias": []},
    "escopo": {"papel": "admin", "id_loja": None, "pode_escolher_loja": True},
}
FILA_VAZIA = {"total_aberto": 0, "sem_resposta": 0, "urgentes": 0, "itens": []}

ROTAS = ["/dashboard/atendimento", "/dashboard/atendimento/fila"]


@pytest.fixture
def chamadas(monkeypatch):
    """Troca o service por um gravador: o que importa aqui e o que o router decide."""
    registro = []

    def dashboard(conexao, usuario, *, inicio, fim, filtro):
        registro.append(("dashboard", usuario, inicio, fim, filtro))
        return DASHBOARD_VAZIO

    def fila(conexao, filtro, *, limit, offset):
        registro.append(("fila", filtro, limit, offset))
        return FILA_VAZIA

    monkeypatch.setattr(service, "montar_dashboard", dashboard)
    monkeypatch.setattr(service, "montar_fila", fila)
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


def cabecalho(par: ParDeChaves, papel: Papel | None, loja=LOJA_A) -> dict[str, str]:
    claims = {}
    if papel is not None:
        claims["papel"] = papel.value
        if papel is not Papel.ADMIN:
            claims["loja_id"] = str(loja)
    return {"Authorization": f"Bearer {par.emitir(**claims)}"}


def buscar(cliente, rota, cabecalhos=None, **parametros):
    base = PERIODO if rota == ROTAS[0] else {}
    return cliente.get(rota, params={**base, **parametros}, headers=cabecalhos)


@pytest.mark.parametrize("rota", ROTAS)
def test_sem_token_responde_401(cliente, rota):
    assert buscar(cliente, rota).status_code == 401


@pytest.mark.parametrize("rota", ROTAS)
@pytest.mark.parametrize("papel", [None, Papel.OPERADOR_ESTOQUE])
def test_cliente_e_operador_de_estoque_nao_entram(cliente, par, rota, papel):
    resposta = buscar(cliente, rota, cabecalho(par, papel))
    assert resposta.status_code == 403


@pytest.mark.parametrize("rota", ROTAS)
@pytest.mark.parametrize("papel", [Papel.ATENDENTE, Papel.GERENTE_LOJA, Papel.ADMIN])
def test_equipe_de_atendimento_entra(cliente, par, rota, papel):
    assert buscar(cliente, rota, cabecalho(par, papel)).status_code == 200


@pytest.mark.parametrize("rota", ROTAS)
@pytest.mark.parametrize("papel", [Papel.ATENDENTE, Papel.GERENTE_LOJA])
def test_atendente_e_gerente_nao_pedem_outra_loja(cliente, par, chamadas, rota, papel):
    resposta = buscar(cliente, rota, cabecalho(par, papel), id_loja=str(LOJA_B))
    assert resposta.status_code == 403
    assert chamadas == []  # nem chegou a consultar o banco


@pytest.mark.parametrize("rota", ROTAS)
def test_atendente_sem_filtro_usa_a_loja_do_token(cliente, par, chamadas, rota):
    buscar(cliente, rota, cabecalho(par, Papel.ATENDENTE))
    filtro = chamadas[0][4] if rota == ROTAS[0] else chamadas[0][1]
    assert filtro.id_loja == LOJA_A


@pytest.mark.parametrize("rota", ROTAS)
def test_atendente_pode_pedir_a_propria_loja(cliente, par, rota):
    resposta = buscar(cliente, rota, cabecalho(par, Papel.ATENDENTE), id_loja=str(LOJA_A))
    assert resposta.status_code == 200


@pytest.mark.parametrize("rota", ROTAS)
def test_admin_ve_a_rede_ou_filtra_por_loja(cliente, par, chamadas, rota):
    buscar(cliente, rota, cabecalho(par, Papel.ADMIN))
    buscar(cliente, rota, cabecalho(par, Papel.ADMIN), id_loja=str(LOJA_B))
    indice = 4 if rota == ROTAS[0] else 1
    assert chamadas[0][indice].id_loja is None
    assert chamadas[1][indice].id_loja == LOJA_B


def test_repassa_periodo_canal_e_categoria(cliente, par, chamadas):
    buscar(
        cliente,
        ROTAS[0],
        cabecalho(par, Papel.ADMIN),
        canal="whatsapp",
        categoria="entrega",
    )
    _, _, inicio, fim, filtro = chamadas[0]
    assert (inicio, fim) == (date(2026, 10, 1), date(2026, 10, 7))
    assert (filtro.canal, filtro.categoria) == ("whatsapp", "entrega")


@pytest.mark.parametrize(
    "parametros",
    [
        {"inicio": "2026-10-07", "fim": "2026-10-01"},  # fim antes do inicio
        {"inicio": "2025-01-01", "fim": "2026-10-01"},  # mais de 400 dias
        {"inicio": "ontem", "fim": "2026-10-01"},
    ],
)
def test_periodo_invalido_responde_422(cliente, par, parametros):
    resposta = cliente.get(ROTAS[0], params=parametros, headers=cabecalho(par, Papel.ADMIN))
    assert resposta.status_code == 422


def test_periodo_e_obrigatorio(cliente, par):
    resposta = cliente.get(ROTAS[0], headers=cabecalho(par, Papel.ADMIN))
    assert resposta.status_code == 422


@pytest.mark.parametrize("rota", ROTAS)
@pytest.mark.parametrize(
    "parametros",
    [
        {"canal": "WhatsApp"},  # so codigos em minusculas
        {"canal": "x'; DROP TABLE atendimento; --"},
        {"categoria": "a" * 41},
        {"id_loja": "nao-e-uuid"},
    ],
)
def test_filtros_fora_do_formato_respondem_422(cliente, par, rota, parametros):
    resposta = buscar(cliente, rota, cabecalho(par, Papel.ADMIN), **parametros)
    assert resposta.status_code == 422


@pytest.mark.parametrize("parametros", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
def test_paginacao_da_fila_tem_limites(cliente, par, parametros):
    resposta = buscar(cliente, ROTAS[1], cabecalho(par, Papel.ADMIN), **parametros)
    assert resposta.status_code == 422


def test_fila_usa_pagina_padrao_de_20(cliente, par, chamadas):
    buscar(cliente, ROTAS[1], cabecalho(par, Papel.ADMIN))
    assert chamadas[0][2:] == (20, 0)


def test_dashboard_exige_token_mesmo_com_a_flag_de_autenticacao_desligada(par, chamadas):
    app = criar_app(
        Settings(
            _env_file=None,
            database_url=DATABASE_URL_TESTE,
            supabase_url=SUPABASE_URL,
            autenticacao_obrigatoria=False,
        )
    )
    app.state.provedor_chaves = provedor_para(par)
    app.dependency_overrides[get_executar] = lambda: lambda operacao: operacao(None)
    assert TestClient(app).get(ROTAS[0], params=PERIODO).status_code == 401


def test_rotas_aparecem_no_openapi(cliente):
    caminhos = cliente.get("/openapi.json").json()["paths"]
    assert set(ROTAS) <= set(caminhos)


class TestRegrasDoService:
    def test_periodo_anterior_com_a_mesma_duracao(self):
        assert service.periodo_anterior(date(2026, 10, 1), date(2026, 10, 7)) == (
            date(2026, 9, 24),
            date(2026, 9, 30),
        )
        assert service.periodo_anterior(date(2026, 10, 7), date(2026, 10, 7)) == (
            date(2026, 10, 6),
            date(2026, 10, 6),
        )

    def test_limite_de_400_dias_e_inclusivo(self):
        inicio = date(2026, 1, 1)
        service.validar_periodo(inicio, inicio + timedelta(days=399))  # 400 dias: aceito
        with pytest.raises(PeriodoLongoDemais):
            service.validar_periodo(inicio, inicio + timedelta(days=400))

    def test_fim_antes_do_inicio_e_recusado(self):
        with pytest.raises(PeriodoInvalido):
            service.validar_periodo(date(2026, 10, 2), date(2026, 10, 1))
