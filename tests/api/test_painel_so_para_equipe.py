"""Rede de seguranca: as rotas do painel e dos dashboards so abrem para quem tem cargo.

Com um token valido de cliente (sem cargo) NENHUMA rota do painel pode responder 2xx, e cada
papel da equipe so entra nas areas dele. Percorre todas as rotas registradas, entao uma rota
nova que esqueca a trava de papel faz este teste quebrar.
"""

import re
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.db import get_executar
from app.core.papeis import Papel
from app.main import criar_app
from tests.auth_util import SUPABASE_URL, ParDeChaves, provedor_para
from tests.conftest import DATABASE_URL_TESTE

PREFIXOS_DA_EQUIPE = ("/api/v1/painel/", "/dashboard/")
LOJA = uuid4()
METODOS = {"get", "post", "put", "patch", "delete"}


def rotas_do_painel(app):
    for caminho, operacoes in app.openapi()["paths"].items():
        if caminho.startswith(PREFIXOS_DA_EQUIPE):
            for metodo in operacoes:
                if metodo in METODOS:
                    yield metodo.upper(), caminho


@pytest.fixture(scope="module")
def par():
    return ParDeChaves()


@pytest.fixture(scope="module")
def cliente(par):
    app = criar_app(
        Settings(_env_file=None, database_url=DATABASE_URL_TESTE, supabase_url=SUPABASE_URL)
    )
    app.state.provedor_chaves = provedor_para(par)

    def sem_banco():
        def executar(_operacao):
            raise AssertionError("rota do painel chegou ao banco para quem nao podia")

        return executar

    app.dependency_overrides[get_executar] = sem_banco
    return TestClient(app, raise_server_exceptions=False)


def cabecalho(par, papel: Papel | None) -> dict[str, str]:
    claims = {}
    if papel is not None:
        claims["papel"] = papel.value
        if papel is not Papel.ADMIN:
            claims["loja_id"] = str(LOJA)
    return {"Authorization": f"Bearer {par.emitir(**claims)}"}


def chamar(cliente, metodo, caminho, headers):
    url = re.sub(r"\{[^}]+\}", str(uuid4()), caminho)
    # Parametros obrigatorios de consulta (periodos) para a validacao nao mascarar a trava.
    return cliente.request(
        metodo,
        url,
        headers=headers,
        json={} if metodo != "GET" else None,
        params={"inicio": "2026-09-01", "fim": "2026-09-30"},
    )


def test_ha_rotas_do_painel_para_verificar(cliente):
    assert len(list(rotas_do_painel(cliente.app))) > 30


def test_cliente_logado_nao_entra_em_nenhuma_rota_do_painel(cliente, par):
    liberadas = []
    for metodo, caminho in rotas_do_painel(cliente.app):
        resposta = chamar(cliente, metodo, caminho, cabecalho(par, None))
        if resposta.status_code != 403:
            liberadas.append(f"{metodo} {caminho} -> {resposta.status_code}")
    assert liberadas == [], "cliente passou numa rota do equipe:\n" + "\n".join(liberadas)


@pytest.mark.parametrize(
    ("papel", "areas_negadas"),
    [
        # O atendente nao toca em estoque, vendas nem pendencias da gerencia.
        (Papel.ATENDENTE, ("/api/v1/painel/estoque", "/api/v1/painel/gerencia")),
        # O operador de estoque nao atende chamados nem ve dashboards de vendas/atendimento.
        (
            Papel.OPERADOR_ESTOQUE,
            (
                "/api/v1/painel/atendimentos",
                "/api/v1/painel/chat",
                "/api/v1/painel/clientes",
                "/api/v1/painel/gerencia",
                "/dashboard/",
            ),
        ),
    ],
)
def test_cada_papel_so_entra_na_propria_area(cliente, par, papel, areas_negadas):
    liberadas = []
    for metodo, caminho in rotas_do_painel(cliente.app):
        if caminho.startswith(areas_negadas):
            resposta = chamar(cliente, metodo, caminho, cabecalho(par, papel))
            if resposta.status_code != 403:
                liberadas.append(f"{metodo} {caminho} -> {resposta.status_code}")
    assert liberadas == [], f"{papel.value} passou onde nao devia:\n" + "\n".join(liberadas)


def test_so_a_gestao_decide_ajuste_define_minimo_e_ve_a_gerencia(cliente, par):
    so_gestao = (
        ("POST", "/api/v1/painel/estoque/ajustes/{id}/aprovar"),
        ("POST", "/api/v1/painel/estoque/ajustes/{id}/recusar"),
        ("GET", "/api/v1/painel/estoque/minimos"),
        ("PUT", "/api/v1/painel/estoque/minimos"),
    )
    for metodo, caminho in so_gestao:
        for papel in (Papel.ATENDENTE, Papel.OPERADOR_ESTOQUE):
            resposta = chamar(cliente, metodo, caminho, cabecalho(par, papel))
            assert resposta.status_code == 403, (metodo, caminho, papel)


def test_a_rede_e_a_gestao_do_admin_nao_abrem_para_os_demais(cliente, par):
    for papel in (Papel.GERENTE_LOJA, Papel.ATENDENTE, Papel.OPERADOR_ESTOQUE):
        for metodo, caminho in (
            ("GET", "/api/v1/painel/gerencia/rede"),
            ("GET", "/api/v1/painel/gestao/usuarios"),
            ("PATCH", "/api/v1/painel/gestao/usuarios/{id}"),
            ("GET", "/api/v1/painel/gestao/catalogo"),
            ("POST", "/api/v1/painel/gestao/catalogo"),
            ("PATCH", "/api/v1/painel/gestao/catalogo/{id}"),
            ("DELETE", "/api/v1/painel/gestao/catalogo/{id}"),
            ("GET", "/api/v1/painel/gestao/auditoria"),
            ("GET", "/api/v1/painel/gestao/integracoes"),
            ("POST", "/api/v1/painel/gestao/integracoes/registros/{id}/mapear"),
        ):
            resposta = chamar(cliente, metodo, caminho, cabecalho(par, papel))
            assert resposta.status_code == 403, (papel, caminho)
