"""Rotas do chat ao vivo: papel, escopo, validacao e erros, sem banco."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.chamados import repositorio as repo_chamados
from app.chamados.erros import ChamadoFinalizado, ChamadoNaoEncontrado
from app.chat import service
from app.chat.erros import MensagemDeReferenciaInexistente
from app.core.config import Settings
from app.core.db import get_executar
from app.core.papeis import Papel
from app.main import criar_app
from tests.auth_util import SUPABASE_URL, ParDeChaves, provedor_para
from tests.conftest import DATABASE_URL_TESTE

LOJA_A, LOJA_B = uuid4(), uuid4()
ID_USUARIO = uuid4()
ID = uuid4()
BASE = "/api/v1/painel/chat/conversas"

OPCAO = {"codigo": "x", "nome": "X"}
LISTA = {"total": 0, "itens": []}
RESUMO = {"fila": 1, "minhas": 2, "com_nao_lidas": 3, "nao_lidas": 4, "aguardando_resposta": 5}
SESSAO = {
    "id_atendimento": str(ID),
    "topico": f"chamado:{ID}",
    "canal_privado": True,
    "filtro_mensagens": f"id_atendimento=eq.{ID}",
    "eu": {"id_usuario": str(ID_USUARIO), "nome": "Rafael", "papel": "atendente"},
    "status": OPCAO,
    "id_usuario_responsavel": None,
    "responsavel_nome": None,
    "sou_responsavel": False,
    "pode_responder": True,
    "motivo_bloqueio": None,
    "ultimo_id_mensagem": None,
    "nao_lidas": 0,
}
MENSAGEM = {
    "id_mensagem": str(uuid4()),
    "autor": "atendente",
    "nome": "Rafael",
    "texto": "Ola",
    "enviada_em": "2026-10-07T12:05:00+00:00",
}
MENSAGENS = {"mensagens": [MENSAGEM], "ultimo_id_mensagem": MENSAGEM["id_mensagem"]}


@pytest.fixture
def chamadas(monkeypatch):
    registro = []
    monkeypatch.setattr(repo_chamados, "id_usuario_ativo", lambda _c, _a: ID_USUARIO)

    def grava(nome, retorno):
        def falso(*args, **kwargs):
            registro.append((nome, args, kwargs))
            return retorno

        monkeypatch.setattr(service, nome, falso)

    grava("listar", LISTA)
    grava("resumo", RESUMO)
    grava("sessao", SESSAO)
    grava("mensagens", MENSAGENS)
    grava("enviar_mensagem", MENSAGEM)
    grava("marcar_lido", {"nao_lidas": 0})
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


ROTAS = [
    ("GET", ""),
    ("GET", "/resumo"),
    ("GET", f"/{ID}/sessao"),
    ("GET", f"/{ID}/mensagens"),
    ("POST", f"/{ID}/mensagens"),
    ("POST", f"/{ID}/lido"),
]


def chamar(cliente, metodo, caminho, cabecalhos=None, **params):
    corpo = {"texto": "Ola"} if (metodo, caminho) == ("POST", f"/{ID}/mensagens") else None
    return cliente.request(metodo, BASE + caminho, json=corpo, headers=cabecalhos, params=params)


@pytest.mark.parametrize(("metodo", "caminho"), ROTAS)
def test_sem_token_responde_401(cliente, metodo, caminho):
    assert chamar(cliente, metodo, caminho).status_code == 401


@pytest.mark.parametrize(("metodo", "caminho"), ROTAS)
@pytest.mark.parametrize("papel", [None, Papel.OPERADOR_ESTOQUE])
def test_cliente_e_operador_de_estoque_nao_entram(cliente, par, metodo, caminho, papel):
    assert chamar(cliente, metodo, caminho, token(par, papel)).status_code == 403


@pytest.mark.parametrize(("metodo", "caminho"), ROTAS)
@pytest.mark.parametrize("papel", [Papel.ATENDENTE, Papel.GERENTE_LOJA, Papel.ADMIN])
def test_equipe_de_atendimento_entra(cliente, par, metodo, caminho, papel):
    assert chamar(cliente, metodo, caminho, token(par, papel)).status_code in (200, 201)


@pytest.mark.parametrize("caminho", ["", "/resumo"])
@pytest.mark.parametrize("papel", [Papel.ATENDENTE, Papel.GERENTE_LOJA])
def test_atendente_e_gerente_nao_pedem_outra_loja(cliente, par, chamadas, caminho, papel):
    resposta = chamar(cliente, "GET", caminho, token(par, papel), id_loja=str(LOJA_B))
    assert resposta.status_code == 403
    assert chamadas == []


def test_escopo_da_equipe_e_a_loja_do_token_mais_os_sem_loja(cliente, par, chamadas):
    chamar(cliente, "GET", "", token(par, Papel.ATENDENTE))
    escopo = chamadas[0][1][1]
    assert (escopo.id_loja, escopo.incluir_sem_loja, escopo.id_usuario) == (
        LOJA_A,
        True,
        ID_USUARIO,
    )


def test_admin_ve_a_rede_ou_filtra_uma_loja(cliente, par, chamadas):
    chamar(cliente, "GET", "", token(par, Papel.ADMIN))
    chamar(cliente, "GET", "", token(par, Papel.ADMIN), id_loja=str(LOJA_B))
    assert chamadas[0][1][1].id_loja is None and chamadas[1][1][1].id_loja == LOJA_B


def test_conta_sem_cadastro_ativo_leva_403(cliente, par, monkeypatch):
    monkeypatch.setattr(repo_chamados, "id_usuario_ativo", lambda _c, _a: None)
    assert chamar(cliente, "GET", "", token(par, Papel.ATENDENTE)).status_code == 403


def test_padroes_e_repasse_da_caixa(cliente, par, chamadas):
    chamar(cliente, "GET", "", token(par, Papel.ATENDENTE))
    assert chamadas[0][2] == {"secao": "todas", "apenas_nao_lidas": False, "limit": 20, "offset": 0}
    chamar(
        cliente,
        "GET",
        "",
        token(par, Papel.ATENDENTE),
        secao="minhas",
        apenas_nao_lidas="true",
        limit=50,
        offset=5,
    )
    assert chamadas[1][2] == {"secao": "minhas", "apenas_nao_lidas": True, "limit": 50, "offset": 5}


@pytest.mark.parametrize(
    "params",
    [
        {"secao": "outra"},
        {"apenas_nao_lidas": "talvez"},
        {"id_loja": "nao-e-uuid"},
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
    ],
)
def test_parametros_invalidos_respondem_422(cliente, par, params):
    assert chamar(cliente, "GET", "", token(par, Papel.ADMIN), **params).status_code == 422


def test_cursor_e_limite_das_mensagens(cliente, par, chamadas):
    apos = uuid4()
    chamar(
        cliente, "GET", f"/{ID}/mensagens", token(par, Papel.ATENDENTE), apos=str(apos), limit=30
    )
    assert chamadas[0][2] == {"apos": apos, "limit": 30}
    chamar(cliente, "GET", f"/{ID}/mensagens", token(par, Papel.ATENDENTE))
    assert chamadas[1][2] == {"apos": None, "limit": 100}


@pytest.mark.parametrize("params", [{"apos": "abc"}, {"limit": 0}, {"limit": 201}])
def test_cursor_invalido_responde_422(cliente, par, params):
    resposta = chamar(cliente, "GET", f"/{ID}/mensagens", token(par, Papel.ATENDENTE), **params)
    assert resposta.status_code == 422


@pytest.mark.parametrize("caminho", ["/abc/sessao", "/abc/mensagens", "/abc/lido"])
def test_id_que_nao_e_uuid_responde_422(cliente, par, caminho):
    metodo = "POST" if caminho.endswith("/lido") else "GET"
    assert chamar(cliente, metodo, caminho, token(par, Papel.ADMIN)).status_code == 422


@pytest.mark.parametrize(
    "corpo",
    [
        {},
        {"texto": ""},
        {"texto": "   "},
        {"texto": "a" * 4001},
        {"texto": "Ola", "id_usuario_remetente": str(uuid4())},
        {"texto": "Ola", "papel": "admin"},
    ],
)
def test_corpo_da_mensagem_e_validado_e_nao_aceita_identidade(cliente, par, chamadas, corpo):
    resposta = cliente.post(
        f"{BASE}/{ID}/mensagens", json=corpo, headers=token(par, Papel.ATENDENTE)
    )
    assert resposta.status_code == 422
    assert not [c for c in chamadas if c[0] == "enviar_mensagem"]


def test_sessao_diz_o_canal_privado_e_o_filtro_de_mensagens(cliente, par):
    resposta = chamar(cliente, "GET", f"/{ID}/sessao", token(par, Papel.ATENDENTE))
    corpo = resposta.json()
    assert corpo["topico"] == f"chamado:{ID}" and corpo["canal_privado"] is True
    assert corpo["filtro_mensagens"] == f"id_atendimento=eq.{ID}"


@pytest.mark.parametrize(
    ("nome", "erro", "status"),
    [
        ("sessao", ChamadoNaoEncontrado(), 404),
        ("mensagens", MensagemDeReferenciaInexistente(), 404),
        ("enviar_mensagem", ChamadoFinalizado(), 409),
        ("marcar_lido", ChamadoNaoEncontrado(), 404),
    ],
)
def test_erros_de_negocio_viram_o_status_certo(cliente, par, monkeypatch, nome, erro, status):
    def falha(*_a, **_k):
        raise erro

    monkeypatch.setattr(service, nome, falha)
    chamadas = {
        "sessao": ("GET", f"/{ID}/sessao"),
        "mensagens": ("GET", f"/{ID}/mensagens"),
        "enviar_mensagem": ("POST", f"/{ID}/mensagens"),
        "marcar_lido": ("POST", f"/{ID}/lido"),
    }
    metodo, caminho = chamadas[nome]
    resposta = chamar(cliente, metodo, caminho, token(par, Papel.ATENDENTE))
    assert resposta.status_code == status
    assert resposta.json()["detail"]


def test_resumo_e_sessao_nao_viram_id(cliente, par):
    """/resumo precisa vir antes de /{id}, senao seria lido como um uuid invalido."""
    assert chamar(cliente, "GET", "/resumo", token(par, Papel.ATENDENTE)).status_code == 200


def test_rotas_estao_sob_api_v1(cliente):
    caminhos = set(cliente.app.openapi()["paths"])
    esperados = {
        BASE,
        f"{BASE}/resumo",
        f"{BASE}/{{id_atendimento}}/sessao",
        f"{BASE}/{{id_atendimento}}/mensagens",
        f"{BASE}/{{id_atendimento}}/lido",
    }
    assert esperados <= caminhos


class TestRegrasPuras:
    def test_topico_do_canal_segue_o_formato_das_policies(self):
        assert service.topico_do_canal(ID) == f"chamado:{ID}"

    @pytest.mark.parametrize(
        ("status", "responsavel", "papel", "esperado"),
        [
            ("aberto", None, Papel.ATENDENTE, True),
            ("em_andamento", "eu", Papel.ATENDENTE, True),
            ("em_andamento", "outro", Papel.ATENDENTE, False),
            ("em_andamento", "outro", Papel.GERENTE_LOJA, True),
            ("em_andamento", "outro", Papel.ADMIN, True),
            ("resolvido", None, Papel.ADMIN, False),
            ("encerrado", "eu", Papel.ATENDENTE, False),
            ("cancelado", None, Papel.GERENTE_LOJA, False),
        ],
    )
    def test_regra_de_resposta(self, status, responsavel, papel, esperado):
        from app.core.papeis import UsuarioAtual

        eu, outro = uuid4(), uuid4()
        id_resp = {None: None, "eu": eu, "outro": outro}[responsavel]
        usuario = UsuarioAtual(
            id_auth=uuid4(), papel=papel, id_loja=None if papel is Papel.ADMIN else LOJA_A
        )
        pode, motivo = service.regra_de_resposta(status, id_resp, "Fulano", eu, usuario)
        assert pode is esperado
        assert (motivo is None) is esperado
