"""Base dos assistentes e das automacoes (Entrega 4), sem banco: autenticacao do n8n, escopo das
consultas novas, horario das lojas, preferencia de mensagens e as contas puras."""

from collections import namedtuple
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.automacoes import service as automacoes
from app.automacoes.schemas import ResumoSemanal
from app.cliente import service as cliente_service
from app.cliente.repositorio import situacao_da_categoria
from app.cliente.vencimento_pontos import a_vencer_por_cliente
from app.core.config import Settings
from app.core.db import get_executar
from app.core.horario import HorarioFuncionamento
from app.core.papeis import Papel
from app.gerencia import service as gerencia
from app.gestao import lojas
from app.main import criar_app
from scripts.importar_aceita_mensagens import aceita, cpf
from tests.auth_util import SUPABASE_URL, ParDeChaves, provedor_para
from tests.conftest import DATABASE_URL_TESTE

CHAVE = "chave-de-teste-do-n8n"
LOJA_A, LOJA_B = uuid4(), uuid4()
AUTOMACOES = "/api/v1/automacoes"
GERENCIA = "/api/v1/painel/gerencia"

PARADO = {
    "dias": 60,
    "criterio": "x",
    "total_itens": 0,
    "total_unidades": 0,
    "total_valor": 0.0,
    "itens": [],
}
PONTOS = {"dias": 30, "criterio": "x", "clientes": 0, "pontos": 0, "por_data": []}
A_AVISAR = {"canal": "email", "dias": 30, "criterio": "x", "total": 0, "clientes": []}


@pytest.fixture
def chamadas(monkeypatch):
    registro = []

    def grava(modulo, nome, retorno):
        def falso(*args, **kwargs):
            registro.append((nome, args, kwargs))
            return retorno

        monkeypatch.setattr(modulo, nome, falso)

    grava(gerencia, "montar_estoque_parado", PARADO)
    grava(gerencia, "montar_pontos_a_vencer", PONTOS)
    grava(automacoes, "clientes_a_avisar", A_AVISAR)
    grava(automacoes, "registrar_avisos", {"recebidos": 1, "gravados": 1})
    grava(cliente_service, "alterar_preferencias", {"aceita_mensagens": False})
    grava(lojas, "alterar_horario", {"id_loja": str(LOJA_A), "horario_funcionamento": None})
    return registro


@pytest.fixture
def par():
    return ParDeChaves()


def montar_cliente(par, **config):
    app = criar_app(
        Settings(
            _env_file=None, database_url=DATABASE_URL_TESTE, supabase_url=SUPABASE_URL, **config
        )
    )
    app.state.provedor_chaves = provedor_para(par)
    app.dependency_overrides[get_executar] = lambda: lambda operacao: operacao(None)
    return TestClient(app)


@pytest.fixture
def cliente(par, chamadas):
    return montar_cliente(par, chave_automacao=CHAVE)


def token(par, papel, loja=LOJA_A):
    claims = {}
    if papel is not None:
        claims["papel"] = papel.value
        if papel is not Papel.ADMIN:
            claims["loja_id"] = str(loja)
    return {"Authorization": f"Bearer {par.emitir(**claims)}"}


# ---------------------------------------------------------------- automacoes (n8n)


def test_automacao_sem_chave_e_401(cliente, chamadas):
    assert cliente.get(AUTOMACOES + "/pontos-a-vencer").status_code == 401
    assert chamadas == []


def test_automacao_com_chave_errada_e_401(cliente, chamadas):
    resposta = cliente.get(AUTOMACOES + "/pontos-a-vencer", headers={"X-Chave-Automacao": "outra"})
    assert resposta.status_code == 401
    assert chamadas == []


def test_token_de_pessoa_nao_abre_automacao(cliente, par, chamadas):
    resposta = cliente.get(AUTOMACOES + "/pontos-a-vencer", headers=token(par, Papel.ADMIN))
    assert resposta.status_code == 401
    assert chamadas == []


def test_servidor_sem_chave_configurada_e_503(par, chamadas):
    resposta = montar_cliente(par).get(
        AUTOMACOES + "/pontos-a-vencer", headers={"X-Chave-Automacao": CHAVE}
    )
    assert resposta.status_code == 503
    assert chamadas == []


def test_automacao_com_chave_certa_passa_canal_e_dias(cliente, chamadas):
    resposta = cliente.get(
        AUTOMACOES + "/pontos-a-vencer",
        params={"canal": "whatsapp", "dias": 15},
        headers={"X-Chave-Automacao": CHAVE},
    )
    assert resposta.status_code == 200
    assert chamadas[0][2] == {"dias": 15, "canal": "whatsapp"}


def test_canal_desconhecido_e_422(cliente):
    resposta = cliente.get(
        AUTOMACOES + "/pontos-a-vencer",
        params={"canal": "sms"},
        headers={"X-Chave-Automacao": CHAVE},
    )
    assert resposta.status_code == 422


def test_registrar_avisos_valida_o_corpo(cliente, chamadas):
    cabecalho = {"X-Chave-Automacao": CHAVE}
    vazio = cliente.post(
        AUTOMACOES + "/avisos-pontos", json={"canal": "email", "avisos": []}, headers=cabecalho
    )
    assert vazio.status_code == 422
    aviso = {"id_cliente": str(uuid4()), "vence_em": "2026-11-20T03:00:00+00:00", "pontos": 120}
    ok = cliente.post(
        AUTOMACOES + "/avisos-pontos", json={"canal": "email", "avisos": [aviso]}, headers=cabecalho
    )
    assert ok.status_code == 200
    assert ok.json() == {"recebidos": 1, "gravados": 1}


def test_semana_fechada_e_segunda_a_domingo_anterior():
    # 27/10/2026 e uma terca: a ultima semana fechada vai de 19 a 25/10.
    assert automacoes.semana_fechada(date(2026, 10, 27)) == (date(2026, 10, 19), date(2026, 10, 25))
    # Numa segunda, a semana que acabou de fechar e a de ontem.
    assert automacoes.semana_fechada(date(2026, 10, 26)) == (date(2026, 10, 19), date(2026, 10, 25))


def test_vendas_da_semana_compara_e_mostra_loja_sem_venda():
    loja_sem_vendas = uuid4()
    loja_sem_vendas_no_periodo = uuid4()
    atual = {LOJA_A: {"faturamento": 1100, "pedidos": 11, "faturamento_online": 100}}
    anterior = {
        LOJA_A: {"faturamento": 1000, "pedidos": 10},
        LOJA_B: {"faturamento": 500, "pedidos": 5},
    }
    lojas_ = automacoes._vendas_da_semana(
        atual,
        anterior,
        {
            LOJA_A: "Barra",
            LOJA_B: "Savassi",
            loja_sem_vendas: "Loja sem venda anterior",
            loja_sem_vendas_no_periodo: "Loja sem venda no período",
        },
    )
    assert [(x["loja"], x["faturamento"], x["variacao"]) for x in lojas_] == [
        ("Barra", 1100.0, 0.1),
        ("Loja sem venda anterior", 0.0, None),
        ("Loja sem venda no período", 0.0, None),
        ("Savassi", 0.0, -1.0),
    ]


def test_resumo_semanal_da_loja_filtra_estoque_e_omite_pontos(monkeypatch):
    filtros_vendas = []
    filtros_estoque = []
    filtros_indicadores = []
    monkeypatch.setattr(
        automacoes.repositorio,
        "destinatarios_do_resumo",
        lambda conexao, id_loja: ["gerente@barra.com"],
    )
    monkeypatch.setattr(
        automacoes.repositorio,
        "nome_da_loja_ativa",
        lambda conexao, id_loja: "Barra" if id_loja == LOJA_A else None,
    )

    def vendas_por_loja(conexao, filtro, inicio, fim):
        filtros_vendas.append(filtro)
        return [{"id_loja": LOJA_A, "faturamento": 1200, "pedidos": 12}]

    def estoque_parado(conexao, filtro, **kwargs):
        filtros_estoque.append(filtro)
        return PARADO

    def resumo_vendas(conexao, filtro, inicio, fim):
        filtros_indicadores.append((filtro, inicio, fim))
        return {"faturamento": 1200, "pedidos": 12, "pecas": 18}

    def categorias_mais_vendidas(conexao, filtro, inicio, fim, *, limite):
        filtros_indicadores.append((filtro, inicio, fim, limite))
        return [{"categoria": "Camisas", "unidades": 10, "faturamento": 800}]

    monkeypatch.setattr(automacoes.vendas, "vendas_por_loja", vendas_por_loja)
    monkeypatch.setattr(automacoes.vendas, "resumo", resumo_vendas)
    monkeypatch.setattr(automacoes.vendas, "categorias_mais_vendidas", categorias_mais_vendidas)
    monkeypatch.setattr(gerencia, "montar_estoque_parado", estoque_parado)
    monkeypatch.setattr(
        gerencia,
        "montar_pontos_a_vencer",
        lambda *args, **kwargs: pytest.fail("Relatório individual não deve incluir pontos da rede"),
    )

    resumo = automacoes.resumo_semanal(None, date(2026, 10, 27), id_loja=LOJA_A)

    assert [filtro.id_loja for filtro in filtros_vendas] == [LOJA_A, LOJA_A]
    assert filtros_estoque[0].id_loja == LOJA_A
    assert [loja["loja"] for loja in resumo["lojas"]] == ["Barra"]
    assert resumo["indicadores_unidade"] == {
        "ticket_medio": 100.0,
        "pecas_vendidas": 18,
        "categorias_mais_vendidas": [
            {"categoria": "Camisas", "unidades": 10, "faturamento": 800.0}
        ],
    }
    assert all(item[0].id_loja == LOJA_A for item in filtros_indicadores)
    assert filtros_indicadores[1][3] == automacoes.CATEGORIAS_MAIS_VENDIDAS_NO_RESUMO
    assert resumo["pontos_a_vencer"] is None
    assert resumo["destinatarios"] == ["gerente@barra.com"]
    resposta = ResumoSemanal.model_validate(resumo)
    assert resposta.indicadores_unidade.ticket_medio == 100.0


def test_resumo_semanal_da_rede_nao_calcula_indicadores_exclusivos_da_unidade(monkeypatch):
    monkeypatch.setattr(
        automacoes.repositorio,
        "destinatarios_do_resumo",
        lambda conexao, id_loja: ["admin@lorenzi.com"],
    )
    monkeypatch.setattr(
        automacoes.repositorio, "nomes_das_lojas", lambda conexao: {LOJA_A: "Barra"}
    )
    monkeypatch.setattr(automacoes.vendas, "vendas_por_loja", lambda *args: [])
    monkeypatch.setattr(
        automacoes.vendas,
        "resumo",
        lambda *args: pytest.fail("Resumo da rede não deve buscar indicadores da unidade"),
    )
    monkeypatch.setattr(
        automacoes.vendas,
        "categorias_mais_vendidas",
        lambda *args, **kwargs: pytest.fail("Resumo da rede não deve buscar categorias da unidade"),
    )
    monkeypatch.setattr(gerencia, "montar_estoque_parado", lambda *args, **kwargs: PARADO)
    monkeypatch.setattr(gerencia, "montar_pontos_a_vencer", lambda *args, **kwargs: PONTOS)

    resumo = automacoes.resumo_semanal(None, date(2026, 10, 27))

    assert resumo["indicadores_unidade"] is None
    assert resumo["destinatarios"] == ["admin@lorenzi.com"]


def test_resumo_semanal_rejeita_loja_inativa_ou_desconhecida(monkeypatch):
    monkeypatch.setattr(automacoes.repositorio, "nome_da_loja_ativa", lambda *args: None)

    with pytest.raises(automacoes.LojaDoResumoNaoEncontrada):
        automacoes.resumo_semanal(None, date(2026, 10, 27), id_loja=LOJA_A)


# ---------------------------------------------------------------- consultas da gerencia


def test_estoque_parado_gerente_ve_so_a_propria_loja(cliente, par, chamadas):
    resposta = cliente.get(GERENCIA + "/estoque-parado", headers=token(par, Papel.GERENTE_LOJA))
    assert resposta.status_code == 200
    assert chamadas[0][1][1].id_loja == LOJA_A
    outra = cliente.get(
        GERENCIA + "/estoque-parado",
        params={"id_loja": str(LOJA_B)},
        headers=token(par, Papel.GERENTE_LOJA),
    )
    assert outra.status_code == 403


@pytest.mark.parametrize("papel", [None, Papel.VENDEDOR, Papel.ATENDENTE])
def test_estoque_parado_fora_da_gestao_e_403(cliente, par, chamadas, papel):
    assert cliente.get(GERENCIA + "/estoque-parado", headers=token(par, papel)).status_code == 403
    assert chamadas == []


def test_pontos_a_vencer_so_admin(cliente, par, chamadas):
    gerente = cliente.get(GERENCIA + "/pontos-a-vencer", headers=token(par, Papel.GERENTE_LOJA))
    assert gerente.status_code == 403
    admin = cliente.get(
        GERENCIA + "/pontos-a-vencer", params={"dias": 10}, headers=token(par, Papel.ADMIN)
    )
    assert admin.status_code == 200
    assert chamadas[0][2] == {"dias": 10}


# ---------------------------------------------------------------- horario das lojas

HORARIO = {"seg": {"abre": "10:00", "fecha": "22:00"}, "dom": None}


def test_horario_valido_e_dias_sem_valor_ficam_fechados():
    horario = HorarioFuncionamento.model_validate(HORARIO)
    assert horario.seg.fecha == "22:00"
    assert horario.ter is None


@pytest.mark.parametrize(
    "invalido",
    [
        {"seg": {"abre": "22:00", "fecha": "10:00"}},
        {"seg": {"abre": "25:00", "fecha": "26:00"}},
        {"segunda": {"abre": "10:00", "fecha": "22:00"}},
    ],
)
def test_horario_invalido(invalido):
    with pytest.raises(ValidationError):
        HorarioFuncionamento.model_validate(invalido)


def test_so_admin_altera_horario(cliente, par, chamadas):
    rota = f"/api/v1/painel/gestao/lojas/{LOJA_A}/horario"
    corpo = {"horario_funcionamento": HORARIO}
    gerente = cliente.patch(rota, json=corpo, headers=token(par, Papel.GERENTE_LOJA))
    assert gerente.status_code == 403
    admin = cliente.patch(rota, json=corpo, headers=token(par, Papel.ADMIN))
    assert admin.status_code == 200
    assert chamadas[0][1][2] == LOJA_A


def test_horario_invertido_na_rota_e_422(cliente, par, chamadas):
    rota = f"/api/v1/painel/gestao/lojas/{LOJA_A}/horario"
    corpo = {"horario_funcionamento": {"seg": {"abre": "22:00", "fecha": "10:00"}}}
    assert cliente.patch(rota, json=corpo, headers=token(par, Papel.ADMIN)).status_code == 422
    assert chamadas == []


# ---------------------------------------------------------------- preferencia do cliente


def test_cliente_muda_a_preferencia_de_mensagens(cliente, par, chamadas):
    resposta = cliente.patch(
        "/api/v1/cliente/preferencias", json={"aceita_mensagens": False}, headers=token(par, None)
    )
    assert resposta.status_code == 200
    assert chamadas[0][1][2] is False


def test_preferencia_nao_aceita_campo_extra(cliente, par, chamadas):
    resposta = cliente.patch(
        "/api/v1/cliente/preferencias",
        json={"aceita_mensagens": True, "id_cliente": str(uuid4())},
        headers=token(par, None),
    )
    assert resposta.status_code == 422
    assert chamadas == []


# ---------------------------------------------------------------- contas puras

Mov = namedtuple("Mov", "id_usuario tipo pontos ocorrido_em vence_em id_pedido")
AGORA = datetime(2026, 11, 1, 12, tzinfo=UTC)


def test_pontos_a_vencer_por_cliente_consome_os_mais_antigos():
    ana, bia = uuid4(), uuid4()
    entrou = AGORA - timedelta(days=350)
    movimentos = [
        # Ana: 300 pontos vencem em 15 dias, mas ja resgatou 100 deles.
        Mov(ana, "credito", 300, entrou, entrou + timedelta(days=365), None),
        Mov(ana, "credito", 200, AGORA - timedelta(days=10), AGORA + timedelta(days=355), None),
        Mov(ana, "resgate", -100, AGORA - timedelta(days=5), None, None),
        # Bia: nada vence na janela.
        Mov(bia, "credito", 500, AGORA - timedelta(days=30), AGORA + timedelta(days=335), None),
    ]
    resultado = a_vencer_por_cliente(movimentos, AGORA, timedelta(days=30))
    assert list(resultado) == [ana]
    assert resultado[ana]["pontos_a_vencer"] == 200


def test_situacao_da_categoria():
    assert situacao_da_categoria(1500) == {
        "categoria": "bronze",
        "proxima_categoria": "prata",
        "faltam_para_proxima": 500,
    }
    assert situacao_da_categoria(6000)["proxima_categoria"] == "black"
    assert situacao_da_categoria(12000)["proxima_categoria"] is None


@pytest.mark.parametrize(
    ("valor", "obs", "esperado"),
    [
        ("sim", None, True),
        ("S", None, True),
        (1, None, True),
        ("nao", None, False),
        ("N", None, False),
        (0, None, False),
        ("sim", "Não ligar", False),
        # Sem informacao: fica o default da coluna, que e sim.
        (None, None, None),
        ("x", None, None),
    ],
)
def test_regra_do_consentimento_da_planilha(valor, obs, esperado):
    assert aceita(valor, obs) is esperado


def test_cpf_da_planilha_volta_os_zeros():
    assert cpf("123.456.789-0") == "01234567890"
    assert cpf(None) is None
