# ruff: noqa: E501  (linhas de teste com URLs e payloads)
"""Pela API de verdade, contra um Postgres real: assistente do visitante e login por CPF.

Provedor de LLM e Supabase Auth sao falsos; o banco, as rotas e os limites sao os de verdade.
"""

import json
import random
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.acesso import service as acesso
from app.acesso.router import get_login_auth
from app.assistente.cliente import visitante
from app.assistente.cliente.provedor import ChamadaFeita, RespostaProvedor
from app.assistente.cliente.router import get_fabrica_provedor
from app.core import vigencia
from app.core.config import Settings
from app.main import criar_app
from tests.auth_util import SUPABASE_URL, ParDeChaves, provedor_para

pytestmark = pytest.mark.banco


class ProvedorRoteirizado:
    def __init__(self):
        self.roteiro: list[tuple[str, dict]] = []
        self.texto = "Pronto."
        self.resultados: list[ChamadaFeita] = []
        self.historicos: list[list[dict]] = []

    def responder(self, *, executar, historico, **_):
        self.historicos.append(historico)
        self.resultados = [ChamadaFeita(n, a, executar(n, a)) for n, a in self.roteiro]
        return RespostaProvedor(texto=self.texto, chamadas=list(self.resultados))


class LoginFalso:
    """No lugar do Supabase Auth: confere a senha e diz para qual e-mail foi pedida a sessao."""

    def __init__(self):
        self.pedidos: list[str] = []

    def entrar(self, email, senha):
        self.pedidos.append(email)
        if senha != "Senha123":
            raise acesso.CpfOuSenhaIncorretos
        return {
            "access_token": "token-de-acesso",
            "refresh_token": "token-de-renovacao",
            "expires_in": 3600,
        }


def _cpf():
    return "".join(random.choices("0123456789", k=11))


@pytest.fixture
def cena(banco_migrado, monkeypatch):
    monkeypatch.setattr(vigencia, "ATIVA", True)
    vigencia._conferidos.clear()
    monkeypatch.setattr(visitante, "CONTADOR", visitante.ContadorDiario())
    sufixo = uuid4().hex[:6].upper()
    cpf_cliente, cpf_equipe = _cpf(), _cpf()
    with psycopg.connect(banco_migrado, autocommit=True) as pg:
        loja = pg.execute(
            "INSERT INTO loja (codigo, nome, ativa) VALUES (%s, %s, true) RETURNING id_loja",
            (f"V{sufixo}", f"Loja Visitante {sufixo}"),
        ).fetchone()[0]
        produto = pg.execute(
            "INSERT INTO produto (nome, preco_base, categoria, marca, tecido) VALUES (%s, 159, 'camisas', 'Vulto', 'linho') RETURNING id_produto",
            (f"Camisa Ventura{sufixo}",),
        ).fetchone()[0]
        variacao = pg.execute(
            "INSERT INTO variacao_produto (id_produto, sku, cor, tamanho, preco_venda) VALUES (%s, %s, 'azul', 'M', 159) RETURNING id_variacao",
            (produto, f"VT{sufixo}-AZ-M"),
        ).fetchone()[0]
        pg.execute(
            "INSERT INTO estoque (id_loja, id_variacao, quantidade) VALUES (%s, %s, 3)",
            (loja, variacao),
        )
        # Cliente que se cadastrou pelo site: o trigger do auth.users cria o cadastro.
        email = f"cliente.{sufixo.lower()}@teste.local"
        meta = {
            "cadastro_cliente": "true",
            "nome": "Cliente Cpf",
            "telefone": "11999990000",
            "rua": "Rua A",
            "bairro": "Centro",
            "numero_endereco": "1",
            "cep": "01001000",
            "documento": cpf_cliente,
        }
        auth_cliente = pg.execute(
            "INSERT INTO auth.users (email, raw_user_meta_data) VALUES (%s, %s::jsonb) RETURNING id",
            (email, json.dumps(meta)),
        ).fetchone()[0]
        # Pessoa da equipe com CPF: nao entra por CPF (equipe usa e-mail).
        auth_equipe = uuid4()
        pg.execute(
            "INSERT INTO auth.users (id, email) VALUES (%s, %s)",
            (auth_equipe, f"equipe.{sufixo.lower()}@teste.local"),
        )
        pg.execute(
            "UPDATE usuario SET id_tipo_usuario = (SELECT id_tipo_usuario FROM tipo_usuario WHERE codigo = 'atendente'),"
            " id_loja = %s, documento = %s, rua = NULL, bairro = NULL, numero_endereco = NULL, cep = NULL"
            " WHERE auth_user_id = %s",
            (loja, cpf_equipe, auth_equipe),
        ) if pg.execute(
            "SELECT 1 FROM usuario WHERE auth_user_id = %s", (auth_equipe,)
        ).fetchone() else pg.execute(
            "INSERT INTO usuario (id_tipo_usuario, id_loja, auth_user_id, nome, email, documento) VALUES"
            " ((SELECT id_tipo_usuario FROM tipo_usuario WHERE codigo = 'atendente'), %s, %s, 'Equipe Cpf', %s, %s)",
            (loja, auth_equipe, f"equipe.{sufixo.lower()}@teste.local", cpf_equipe),
        )

        par = ParDeChaves()
        app = criar_app(
            Settings(
                _env_file=None,
                database_url=banco_migrado,
                supabase_url=SUPABASE_URL,
                groq_api_key="chave-falsa-groq",
                gemini_api_key="chave-falsa-gemini",
            )
        )
        app.state.provedor_chaves = provedor_para(par)
        provedor, login = ProvedorRoteirizado(), LoginFalso()
        app.dependency_overrides[get_fabrica_provedor] = lambda: lambda destino, cfg: provedor
        app.dependency_overrides[get_login_auth] = lambda: login
        http = TestClient(app)
        token_cliente = {"Authorization": f"Bearer {par.emitir(sub=str(auth_cliente))}"}

        yield (
            http,
            provedor,
            login,
            pg,
            {
                "cpf": cpf_cliente,
                "cpf_equipe": cpf_equipe,
                "email": email,
                "sku": f"VT{sufixo}-AZ-M",
                "sufixo": sufixo,
                "token": token_cliente,
            },
        )

        auths = [auth_cliente, auth_equipe]
        dos = "SELECT id_usuario FROM usuario WHERE auth_user_id = ANY(%s)"
        pg.execute(f"DELETE FROM conversa_assistente WHERE id_usuario IN ({dos})", (auths,))  # nosec B608
        pg.execute(f"DELETE FROM carrinho WHERE id_cliente IN ({dos})", (auths,))  # nosec B608
        pg.execute("DELETE FROM usuario WHERE auth_user_id = ANY(%s)", (auths,))
        pg.execute("DELETE FROM auth.users WHERE id = ANY(%s)", (auths,))
        pg.execute("DELETE FROM estoque WHERE id_variacao = %s", (variacao,))
        pg.execute("DELETE FROM variacao_produto WHERE id_variacao = %s", (variacao,))
        pg.execute("DELETE FROM produto WHERE id_produto = %s", (produto,))
        pg.execute("DELETE FROM loja WHERE id_loja = %s", (loja,))
    vigencia._conferidos.clear()


VISITANTE = "/api/v1/assistente/visitante/mensagens"
CPF = "/api/v1/acesso/entrar-cpf"


# ------------------------------------------------------------------ assistente do visitante


def test_visitante_sem_token_busca_peca_e_estoque_de_verdade(cena):
    http, provedor, _, _, ids = cena
    provedor.roteiro = [
        ("buscar_produto", {"descricao": f"camisa ventura{ids['sufixo'].lower()}"}),
        ("consultar_estoque", {"sku": ids["sku"]}),
        ("info_loja", {"loja": f"visitante {ids['sufixo']}"}),
    ]
    provedor.texto = "Temos 3 na loja."
    r = http.post(VISITANTE, json={"texto": f"tem estoque do {ids['sku']}?"})
    assert r.status_code == 200, r.text
    assert r.json() == {
        "resposta": "Temos 3 na loja.",
        "sem_resposta": False,
        "precisa_login": False,
    }
    busca, estoque, loja = (c.resultado for c in provedor.resultados)
    assert busca["pecas"][0]["variacoes"][0]["sku"] == ids["sku"]
    assert estoque["total"] == 3
    assert loja["lojas"][0]["nome"].lower().endswith(ids["sufixo"].lower())


def test_visitante_que_pede_a_sacola_recebe_o_pedido_de_login(cena):
    http, provedor, _, pg, ids = cena
    provedor.roteiro = [("montar_carrinho", {"sku": ids["sku"]})]
    corpo = http.post(VISITANTE, json={"texto": "coloca na sacola"}).json()
    assert corpo["precisa_login"] is True
    assert corpo["resposta"] == visitante.TEXTO_PRECISA_LOGIN
    assert (
        pg.execute(
            "SELECT count(*) FROM carrinho c JOIN variacao_produto v USING (id_variacao) WHERE v.sku = %s",
            (ids["sku"],),
        ).fetchone()[0]
        == 0
    )


def test_visitante_tem_teto_diario_por_ip(cena, monkeypatch):
    http, *_ = cena
    monkeypatch.setattr(visitante, "CONTADOR", visitante.ContadorDiario(limite=2))
    ip = {"CF-Connecting-IP": "203.0.113.7"}
    assert http.post(VISITANTE, json={"texto": "oi"}, headers=ip).status_code == 200
    assert http.post(VISITANTE, json={"texto": "oi"}, headers=ip).status_code == 200
    assert http.post(VISITANTE, json={"texto": "oi"}, headers=ip).status_code == 429
    assert (
        http.post(
            VISITANTE, json={"texto": "oi"}, headers={"CF-Connecting-IP": "203.0.113.8"}
        ).status_code
        == 200
    )


def test_depois_do_login_a_conversa_segue_com_o_que_foi_dito_antes(cena):
    http, provedor, _, pg, ids = cena
    historico = [
        {"autor": "usuario", "texto": "tem a camisa ventura azul M?"},
        {"autor": "assistente", "texto": "Temos 3 na loja."},
        {"autor": "usuario", "texto": "coloca na sacola"},
        {"autor": "assistente", "texto": visitante.TEXTO_PRECISA_LOGIN},
    ]
    r = http.post(
        "/api/v1/assistente/cliente/conversas", json={"historico": historico}, headers=ids["token"]
    )
    assert r.status_code == 201, r.text
    conversa = r.json()
    assert [m["texto"] for m in conversa["mensagens"]] == [m["texto"] for m in historico]
    provedor.roteiro = [("montar_carrinho", {"sku": ids["sku"]})]
    resposta = http.post(
        f"/api/v1/assistente/cliente/conversas/{conversa['id_conversa']}/mensagens",
        json={"texto": "coloca na sacola"},
        headers=ids["token"],
    ).json()
    assert resposta["carrinho_alterado"] is True
    # O modelo recebe o que foi dito antes do login.
    assert provedor.historicos[-1][0] == {
        "papel": "usuario",
        "texto": "tem a camisa ventura azul M?",
    }
    # O historico de visitante nao conta no limite diario do cliente.
    hoje = pg.execute(
        "SELECT count(*) FROM mensagem_assistente WHERE id_conversa = %s AND autor = 'usuario'"
        " AND dados->>'origem' IS DISTINCT FROM 'visitante'",
        (conversa["id_conversa"],),
    ).fetchone()[0]
    assert hoje == 1


def test_criar_conversa_sem_corpo_continua_valendo(cena):
    http, *_, ids = cena
    r = http.post("/api/v1/assistente/cliente/conversas", headers=ids["token"])
    assert r.status_code == 201 and r.json()["mensagens"] == []


# ------------------------------------------------------------------ login por CPF


def test_cliente_entra_por_cpf_e_recebe_so_os_tokens(cena):
    http, _, login, _, ids = cena
    r = http.post(
        CPF,
        json={
            "cpf": f"{ids['cpf'][:3]}.{ids['cpf'][3:6]}.{ids['cpf'][6:9]}-{ids['cpf'][9:]}",
            "senha": "Senha123",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json() == {
        "access_token": "token-de-acesso",
        "refresh_token": "token-de-renovacao",
        "expires_in": 3600,
        "token_type": "bearer",
    }
    assert login.pedidos == [ids["email"]]
    assert ids["email"] not in r.text


@pytest.mark.parametrize("caso", ["senha_errada", "cpf_desconhecido", "cpf_da_equipe"])
def test_falhas_do_login_por_cpf_tem_a_mesma_resposta(cena, caso):
    http, _, login, _, ids = cena
    cpf, senha = {
        "senha_errada": (ids["cpf"], "Errada123"),
        "cpf_desconhecido": ("00000000191", "Senha123"),
        "cpf_da_equipe": (ids["cpf_equipe"], "Senha123"),
    }[caso]
    r = http.post(CPF, json={"cpf": cpf, "senha": senha})
    assert r.status_code == 401
    assert r.json()["detail"] == "CPF ou senha incorretos."
    if caso != "senha_errada":
        assert login.pedidos == []
