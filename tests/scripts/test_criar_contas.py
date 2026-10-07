"""O script que cria as contas de acesso: senhas, interpretacao do Supabase e plano sem rede."""

import importlib.util
import json
import string
from pathlib import Path

import httpx
import pytest

from app.core.papeis import Papel

CAMINHO = Path(__file__).resolve().parents[2] / "scripts" / "criar_contas.py"
_spec = importlib.util.spec_from_file_location("criar_contas", CAMINHO)
criar_contas = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(criar_contas)


def test_gera_senha_forte_e_diferente_a_cada_vez():
    senhas = {criar_contas.gerar_senha() for _ in range(200)}
    assert len(senhas) == 200
    for senha in senhas:
        assert len(senha) == 16
        assert any(c in string.ascii_uppercase for c in senha)
        assert any(c in string.ascii_lowercase for c in senha)
        assert any(c in string.digits for c in senha)
        assert any(c in "!#$%*?" for c in senha)


def test_ha_uma_conta_para_cada_tipo_de_usuario():
    papeis = {conta.papel for conta in criar_contas.CONTAS}
    assert papeis == {"cliente", *(p.value for p in Papel)}


def test_equipe_de_loja_recebe_loja_e_admin_e_cliente_nao():
    precisa = {conta.papel: conta.precisa_loja for conta in criar_contas.CONTAS}
    assert precisa == {
        "cliente": False,
        "atendente": True,
        "operador_estoque": True,
        "gerente_loja": True,
        "admin": False,
    }


def test_email_base_gera_enderecos_com_etiqueta_na_mesma_caixa():
    contas = criar_contas.CONTAS
    emails = [criar_contas.email_da(c, "ignorado.com", "pessoa@gmail.com") for c in contas]
    assert emails == [
        "pessoa+cliente@gmail.com",
        "pessoa+atendente@gmail.com",
        "pessoa+operador@gmail.com",
        "pessoa+gerente@gmail.com",
        "pessoa+admin@gmail.com",
    ]


@pytest.mark.parametrize("ruim", ["sem-arroba", "a+b@gmail.com", "a b@gmail.com", "a@semponto"])
def test_email_base_invalido_para_com_erro(ruim, monkeypatch, tmp_path):
    linhas = [
        "SUPABASE_URL=https://abc.supabase.co",
        "SUPABASE_PUBLISHABLE_KEY=k",
        "DATABASE_URL=postgresql://u:p@h/db",
    ]
    (tmp_path / ".env").write_text("\n".join(linhas), encoding="utf-8")
    monkeypatch.setattr(criar_contas, "RAIZ", tmp_path)
    assert criar_contas.main(["--email-base", ruim]) == 2


def test_emails_sao_unicos_e_usam_o_dominio_pedido():
    emails = [criar_contas.email_da(c, "exemplo.com.br") for c in criar_contas.CONTAS]
    assert len(set(emails)) == len(emails)
    assert all(e.endswith("@exemplo.com.br") for e in emails)


USUARIO = {"id": "6f1c3a52-6a4e-4c8e-9a39-0f1f2b6f2f10", "identities": [{"provider": "email"}]}


@pytest.mark.parametrize(
    ("status", "corpo", "esperado"),
    [
        # confirmacao de e-mail desligada: ja volta com sessao
        (200, {"access_token": "t", "user": USUARIO}, (USUARIO["id"], False, True)),
        # confirmacao ligada: usuario sem sessao e sem e-mail confirmado
        (200, {**USUARIO, "email_confirmed_at": None}, (USUARIO["id"], False, False)),
        (
            200,
            {**USUARIO, "email_confirmed_at": "2026-10-07T00:00:00Z"},
            (USUARIO["id"], False, True),
        ),
        # e-mail repetido, nos dois formatos que o Supabase usa
        (422, {"msg": "User already registered"}, (None, True, True)),
        (200, {"id": USUARIO["id"], "identities": []}, (None, True, True)),
    ],
)
def test_interpreta_a_resposta_do_cadastro(status, corpo, esperado):
    r = criar_contas.interpretar_cadastro(status, corpo)
    assert (r.id_auth, r.ja_existia, r.confirmado) == esperado


@pytest.mark.parametrize("status", [400, 429, 500])
def test_erro_do_supabase_vira_excecao_clara(status):
    with pytest.raises(RuntimeError, match="recusou"):
        criar_contas.interpretar_cadastro(
            status, {"msg": "Password should be at least 6 characters"}
        )


def test_resposta_sem_id_e_recusada():
    with pytest.raises(RuntimeError):
        criar_contas.interpretar_cadastro(200, {"user": {}})


def test_cadastro_usa_so_a_chave_publica_e_o_endpoint_de_signup():
    visto = {}

    def atender(request: httpx.Request) -> httpx.Response:
        visto["url"] = str(request.url)
        visto["apikey"] = request.headers["apikey"]
        visto["authorization"] = request.headers.get("authorization")
        visto["corpo"] = json.loads(request.content)
        return httpx.Response(200, json={"access_token": "t", "user": USUARIO})

    with httpx.Client(transport=httpx.MockTransport(atender)) as http:
        r = criar_contas.cadastrar(
            http, "https://x.supabase.co", "chave-publica", "a@b.com", "Senha#123456789a", "Ana"
        )
    assert r.id_auth == USUARIO["id"]
    assert visto["url"] == "https://x.supabase.co/auth/v1/signup"
    assert visto["apikey"] == "chave-publica"
    assert visto["authorization"] is None  # nenhuma service role: so a chave publica do projeto
    assert visto["corpo"] == {
        "email": "a@b.com",
        "password": "Senha#123456789a",
        "data": {"nome": "Ana"},
    }


def test_sem_aplicar_so_mostra_o_plano_e_nao_toca_na_rede(monkeypatch, capsys, tmp_path):
    (tmp_path / ".env").write_text(
        "SUPABASE_URL=https://abc.supabase.co\nSUPABASE_PUBLISHABLE_KEY=k\nDATABASE_URL=postgresql://u:p@h/db\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(criar_contas, "RAIZ", tmp_path)

    def proibido(*_a, **_k):
        raise AssertionError("o modo de plano nao pode abrir conexao nenhuma")

    monkeypatch.setattr(criar_contas.httpx, "Client", proibido)
    monkeypatch.setattr(criar_contas.psycopg, "connect", proibido)

    assert criar_contas.main([]) == 0
    saida = capsys.readouterr().out
    assert "Nada foi alterado" in saida
    assert "admin@casalorenzi.com.br" in saida
    assert "p@h" not in saida  # a senha do banco nunca aparece


def test_sem_env_completo_para_com_erro(monkeypatch, tmp_path, capsys):
    (tmp_path / ".env").write_text("SUPABASE_URL=https://abc.supabase.co\n", encoding="utf-8")
    monkeypatch.setattr(criar_contas, "RAIZ", tmp_path)
    assert criar_contas.main([]) == 2
    assert "Faltam" in capsys.readouterr().err
