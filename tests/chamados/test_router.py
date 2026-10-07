"""Rotas dos chamados do painel: papel, escopo de loja, validacao e erros, sem banco."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.chamados import repositorio, service
from app.chamados.erros import (
    ChamadoFinalizado,
    ChamadoJaAssumido,
    ChamadoNaoEncontrado,
    ChamadoSemResponsavel,
    SemPermissaoNoChamado,
)
from app.core.config import Settings
from app.core.db import get_executar
from app.core.papeis import Papel
from app.main import criar_app
from tests.auth_util import SUPABASE_URL, ParDeChaves, provedor_para
from tests.conftest import DATABASE_URL_TESTE

LOJA_A, LOJA_B = uuid4(), uuid4()
ID_USUARIO = uuid4()
ID = uuid4()
BASE = "/api/v1/painel/atendimentos"

OPCOES = {"status": [], "canais": [], "categorias": [], "prioridades": [], "lojas": []}
RESUMO = {
    "sem_resposta": 1,
    "em_andamento": 2,
    "prioridade_alta": 3,
    "resolvidos": 4,
    "na_fila": 5,
    "meus": 6,
}
LISTA = {"total": 0, "itens": []}
ITEM = {
    "id_atendimento": str(ID),
    "protocolo": "AT-2026-0001",
    "assunto": "Troca de tamanho",
    "cliente_nome": "Helena",
    "categoria": {"codigo": "pedido", "nome": "Pedido"},
    "canal": {"codigo": "site", "nome": "Site"},
    "prioridade": {"codigo": "alta", "nome": "Alta"},
    "status": {"codigo": "em_andamento", "nome": "Em andamento"},
    "id_loja": str(LOJA_A),
    "loja_nome": "Centro",
    "aberto_em": "2026-10-07T12:00:00+00:00",
    "id_usuario_responsavel": str(ID_USUARIO),
    "responsavel_nome": "Rafael",
    "sou_responsavel": True,
}
MENSAGEM = {
    "id_mensagem": str(uuid4()),
    "autor": "atendente",
    "nome": "Rafael",
    "texto": "Ola",
    "enviada_em": "2026-10-07T12:05:00+00:00",
}


@pytest.fixture
def chamadas(monkeypatch):
    """Troca o banco por dubles: o que importa aqui e o que o router decide e repassa."""
    registro = []
    monkeypatch.setattr(repositorio, "id_usuario_ativo", lambda _c, _a: ID_USUARIO)

    def grava(nome, retorno):
        def falso(*args, **kwargs):
            registro.append((nome, args, kwargs))
            return retorno

        monkeypatch.setattr(service, nome, falso)

    grava("opcoes", OPCOES)
    grava("resumo", RESUMO)
    grava("listar", LISTA)
    grava("mensagens", [MENSAGEM])
    grava("enviar_mensagem", MENSAGEM)
    grava("assumir", ITEM)
    grava("resolver", ITEM)
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


def token(par: ParDeChaves, papel: Papel | None, loja=LOJA_A) -> dict[str, str]:
    claims = {}
    if papel is not None:
        claims["papel"] = papel.value
        if papel is not Papel.ADMIN:
            claims["loja_id"] = str(loja)
    return {"Authorization": f"Bearer {par.emitir(**claims)}"}


LEITURAS = [("GET", ""), ("GET", "/opcoes"), ("GET", "/resumo"), ("GET", f"/{ID}/mensagens")]
ESCRITAS = [
    ("POST", f"/{ID}/mensagens", {"texto": "Ola"}),
    ("POST", f"/{ID}/assumir", None),
    ("POST", f"/{ID}/resolver", None),
]
TODAS = [(m, c, None) for m, c in LEITURAS] + ESCRITAS


def chamar(cliente, metodo, caminho, corpo=None, cabecalhos=None, **params):
    return cliente.request(metodo, BASE + caminho, json=corpo, headers=cabecalhos, params=params)


@pytest.mark.parametrize(("metodo", "caminho", "corpo"), TODAS)
def test_sem_token_responde_401(cliente, metodo, caminho, corpo):
    assert chamar(cliente, metodo, caminho, corpo).status_code == 401


@pytest.mark.parametrize(("metodo", "caminho", "corpo"), TODAS)
@pytest.mark.parametrize("papel", [None, Papel.OPERADOR_ESTOQUE])
def test_cliente_e_operador_de_estoque_nao_entram(cliente, par, metodo, caminho, corpo, papel):
    resposta = chamar(cliente, metodo, caminho, corpo, token(par, papel))
    assert resposta.status_code == 403


@pytest.mark.parametrize("papel", [Papel.ATENDENTE, Papel.GERENTE_LOJA, Papel.ADMIN])
def test_equipe_de_atendimento_acessa_leituras_e_escritas(cliente, par, papel):
    for metodo, caminho in [("GET", ""), ("GET", "/opcoes"), ("GET", "/resumo")]:
        assert chamar(cliente, metodo, caminho, None, token(par, papel)).status_code == 200
    assert chamar(cliente, "GET", f"/{ID}/mensagens", None, token(par, papel)).status_code == 200
    for _, caminho, corpo in ESCRITAS:
        resposta = chamar(cliente, "POST", caminho, corpo, token(par, papel))
        assert resposta.status_code in (200, 201), caminho


@pytest.mark.parametrize("caminho", ["", "/opcoes", "/resumo"])
@pytest.mark.parametrize("papel", [Papel.ATENDENTE, Papel.GERENTE_LOJA])
def test_atendente_e_gerente_nao_pedem_outra_loja(cliente, par, chamadas, caminho, papel):
    resposta = chamar(cliente, "GET", caminho, None, token(par, papel), id_loja=str(LOJA_B))
    assert resposta.status_code == 403
    assert chamadas == []


def test_escopo_da_equipe_de_loja_e_a_loja_do_token_mais_os_sem_loja(cliente, par, chamadas):
    chamar(cliente, "GET", "", None, token(par, Papel.ATENDENTE))
    escopo = chamadas[0][1][1]
    assert (escopo.id_loja, escopo.incluir_sem_loja, escopo.id_usuario) == (
        LOJA_A,
        True,
        ID_USUARIO,
    )


def test_admin_ve_a_rede_ou_filtra_por_uma_loja(cliente, par, chamadas):
    chamar(cliente, "GET", "", None, token(par, Papel.ADMIN))
    chamar(cliente, "GET", "", None, token(par, Papel.ADMIN), id_loja=str(LOJA_B))
    rede, so_b = chamadas[0][1][1], chamadas[1][1][1]
    assert (rede.id_loja, rede.incluir_sem_loja) == (None, False)
    assert so_b.id_loja == LOJA_B


def test_conta_sem_cadastro_ativo_leva_403(cliente, par, monkeypatch):
    monkeypatch.setattr(repositorio, "id_usuario_ativo", lambda _c, _a: None)
    resposta = chamar(cliente, "GET", "", None, token(par, Papel.ATENDENTE))
    assert resposta.status_code == 403
    assert "cadastro" in resposta.json()["detail"]


def test_repassa_os_filtros_da_lista(cliente, par, chamadas):
    chamar(
        cliente,
        "GET",
        "",
        None,
        token(par, Papel.ADMIN),
        situacao="em_andamento",
        responsavel="eu",
        prioridade="alta",
        canal="whatsapp",
        categoria="entrega",
        limit=50,
        offset=10,
    )
    assert chamadas[0][2] == {
        "situacao": "em_andamento",
        "responsavel": "eu",
        "prioridade": "alta",
        "canal": "whatsapp",
        "categoria": "entrega",
        "limit": 50,
        "offset": 10,
    }


def test_padroes_da_lista(cliente, par, chamadas):
    chamar(cliente, "GET", "", None, token(par, Papel.ATENDENTE))
    assert chamadas[0][2] == {
        "situacao": "abertos",
        "responsavel": "todos",
        "prioridade": None,
        "canal": None,
        "categoria": None,
        "limit": 20,
        "offset": 0,
    }


@pytest.mark.parametrize(
    "params",
    [
        {"situacao": "qualquer"},
        {"responsavel": "outro"},
        {"prioridade": "critica"},
        {"canal": "WhatsApp"},
        {"canal": "x'; DROP TABLE atendimento; --"},
        {"categoria": "a" * 41},
        {"id_loja": "nao-e-uuid"},
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
    ],
)
def test_filtros_invalidos_respondem_422(cliente, par, params):
    assert chamar(cliente, "GET", "", None, token(par, Papel.ADMIN), **params).status_code == 422


@pytest.mark.parametrize("caminho", ["/abc", "/abc/mensagens", "/abc/assumir", "/abc/resolver"])
def test_id_que_nao_e_uuid_responde_422(cliente, par, caminho):
    metodo = "GET" if caminho in ("/abc", "/abc/mensagens") else "POST"
    assert chamar(cliente, metodo, caminho, None, token(par, Papel.ADMIN)).status_code == 422


@pytest.mark.parametrize(
    "corpo",
    [
        {},
        {"texto": ""},
        {"texto": "   "},
        {"texto": "a" * 4001},
        {"texto": "Ola", "id_usuario_remetente": str(uuid4())},
        {"texto": "Ola", "papel": "admin"},
        {"texto": "Ola", "id_loja": str(LOJA_A)},
        {"texto": 123},
    ],
)
def test_corpo_da_mensagem_e_validado_e_nao_aceita_identidade(cliente, par, chamadas, corpo):
    resposta = chamar(cliente, "POST", f"/{ID}/mensagens", corpo, token(par, Papel.ATENDENTE))
    assert resposta.status_code == 422
    assert not [c for c in chamadas if c[0] == "enviar_mensagem"]


def test_texto_da_mensagem_chega_sem_espacos_nas_pontas(cliente, par, chamadas):
    chamar(cliente, "POST", f"/{ID}/mensagens", {"texto": "  Ola  "}, token(par, Papel.ATENDENTE))
    assert chamadas[0][1][4] == "Ola"


@pytest.mark.parametrize(
    ("erro", "status", "trecho"),
    [
        (ChamadoNaoEncontrado(), 404, "nao encontrado"),
        (ChamadoFinalizado(), 409, "resolvido"),
        (ChamadoJaAssumido("Rafael"), 409, "Rafael ja assumiu"),
        (ChamadoJaAssumido(voce=True), 409, "Voce ja assumiu"),
        (ChamadoSemResponsavel(), 409, "Assuma"),
        (SemPermissaoNoChamado(), 403, "gerente"),
    ],
)
def test_erros_de_negocio_viram_o_status_certo(cliente, par, monkeypatch, erro, status, trecho):
    def falha(*_a, **_k):
        raise erro

    for nome in ("assumir", "resolver", "enviar_mensagem"):
        monkeypatch.setattr(service, nome, falha)
    for caminho, corpo in [
        (f"/{ID}/assumir", None),
        (f"/{ID}/resolver", None),
        (f"/{ID}/mensagens", {"texto": "x"}),
    ]:
        resposta = chamar(cliente, "POST", caminho, corpo, token(par, Papel.ATENDENTE))
        assert resposta.status_code == status
        assert trecho in resposta.json()["detail"]


def test_rotas_estao_sob_api_v1(cliente):
    caminhos = set(cliente.get("/openapi.json").json()["paths"])
    esperados = {
        f"{BASE}",
        f"{BASE}/opcoes",
        f"{BASE}/resumo",
        f"{BASE}/{{id_atendimento}}",
        f"{BASE}/{{id_atendimento}}/mensagens",
        f"{BASE}/{{id_atendimento}}/assumir",
        f"{BASE}/{{id_atendimento}}/resolver",
    }
    assert esperados <= caminhos


def test_opcoes_e_resumo_nao_viram_id(cliente, par, chamadas):
    """/opcoes e /resumo precisam vir antes de /{id}, senao seriam lidos como um uuid invalido."""
    assert chamar(cliente, "GET", "/opcoes", None, token(par, Papel.ATENDENTE)).status_code == 200
    assert chamar(cliente, "GET", "/resumo", None, token(par, Papel.ATENDENTE)).status_code == 200


class TestRegrasDeEscopo:
    def test_resolver_loja_do_atendente_ignora_pedido_vazio(self):
        from app.core.papeis import UsuarioAtual

        usuario = UsuarioAtual(id_auth=uuid4(), papel=Papel.ATENDENTE, id_loja=LOJA_A)
        assert service.resolver_loja(usuario, None) == LOJA_A
        assert service.resolver_loja(usuario, LOJA_A) == LOJA_A
