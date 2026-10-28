"""Login por CPF: ponte para o Supabase Auth com HTTP falso (nenhuma chamada real)."""

import json

import httpx
import pytest

from app.acesso import service
from app.acesso.erros import (
    CpfOuSenhaIncorretos,
    EmailNaoConfirmado,
    LoginIndisponivel,
    MuitasTentativasDeLogin,
)

CHAVE = "chave-service-role-de-teste"
URL = "https://projeto-teste.supabase.co"


def _login(resposta, pedidos):
    def tratar(requisicao):
        pedidos.append(requisicao)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta

    return service.LoginSupabase(
        URL, CHAVE, cliente=httpx.Client(transport=httpx.MockTransport(tratar))
    )


def test_login_pede_a_sessao_com_grant_de_senha_e_chave_so_no_cabecalho():
    pedidos = []
    tokens = {"access_token": "a", "refresh_token": "r", "expires_in": 3600, "token_type": "bearer"}
    sessao = _login(
        httpx.Response(200, json={**tokens, "user": {"email": "x@y.com"}}), pedidos
    ).entrar("x@y.com", "segredo1")
    assert sessao["access_token"] == "a"
    (requisicao,) = pedidos
    assert str(requisicao.url) == f"{URL}/auth/v1/token?grant_type=password"
    assert requisicao.headers["apikey"] == CHAVE
    assert CHAVE not in str(requisicao.url)
    assert json.loads(requisicao.content) == {"email": "x@y.com", "password": "segredo1"}


@pytest.mark.parametrize(
    ("resposta", "erro"),
    [
        (httpx.Response(400, json={"error_code": "invalid_credentials"}), CpfOuSenhaIncorretos),
        (httpx.Response(400, json={"code": "invalid_grant"}), CpfOuSenhaIncorretos),
        (httpx.Response(400, json={"error_code": "email_not_confirmed"}), EmailNaoConfirmado),
        (httpx.Response(429, json={}), MuitasTentativasDeLogin),
        (httpx.Response(500, text="falhou"), LoginIndisponivel),
        (httpx.ConnectError("sem rede"), LoginIndisponivel),
    ],
)
def test_erros_do_auth_viram_respostas_controladas(resposta, erro):
    with pytest.raises(erro):
        _login(resposta, []).entrar("x@y.com", "senha")


def test_cpf_sem_conta_responde_igual_a_senha_errada_sem_chamar_o_auth(monkeypatch):
    monkeypatch.setattr(service, "email_do_cliente", lambda conexao, cpf: None)
    pedidos = []
    with pytest.raises(CpfOuSenhaIncorretos):
        service.entrar_por_cpf(
            None, _login(httpx.Response(200, json={}), pedidos), "52998224725", "x"
        )
    assert pedidos == []


def test_devolve_so_os_tokens_nunca_o_email(monkeypatch):
    monkeypatch.setattr(service, "email_do_cliente", lambda conexao, cpf: "cliente@teste.com")
    corpo = {
        "access_token": "a",
        "refresh_token": "r",
        "expires_in": 3600,
        "user": {"email": "cliente@teste.com"},
    }
    sessao = service.entrar_por_cpf(
        None, _login(httpx.Response(200, json=corpo), []), "52998224725", "x"
    )
    assert sessao == {
        "access_token": "a",
        "refresh_token": "r",
        "expires_in": 3600,
        "token_type": "bearer",
    }
    assert "cliente@teste.com" not in json.dumps(sessao)
