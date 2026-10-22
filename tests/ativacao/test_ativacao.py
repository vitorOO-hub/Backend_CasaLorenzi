"""Ativacao de conta do cliente importado, sem banco real (o SQL tem teste em tests/banco)."""

from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.ativacao import repositorio, service
from app.ativacao.auth_admin import AuthAdminSupabase, get_auth_admin
from app.ativacao.erros import (
    AtivacaoIndisponivel,
    AtivacaoNegada,
    EmailJaNoAuth,
    EmailObrigatorio,
    SenhaRecusada,
)
from app.core.config import Settings
from app.core.db import get_executar
from app.main import criar_app
from tests.conftest import DATABASE_URL_TESTE

CPF = "52998224725"
ID_USUARIO = uuid4()
ID_AUTH = uuid4()


class ConexaoFalsa:
    def __init__(self) -> None:
        self.eventos: list[str] = []

    def commit(self) -> None:
        self.eventos.append("commit")

    def rollback(self) -> None:
        self.eventos.append("rollback")


class AuthFalso:
    def __init__(self, *, erro: Exception | None = None) -> None:
        self.erro = erro
        self.criados: list[tuple[str, str]] = []
        self.apagados: list[UUID] = []

    def criar_usuario(self, email: str, senha: str) -> UUID:
        if self.erro:
            raise self.erro
        self.criados.append((email, senha))
        return ID_AUTH

    def apagar_usuario(self, id_auth: UUID) -> None:
        self.apagados.append(id_auth)


@pytest.fixture
def banco(monkeypatch):
    """Cliente pendente configuravel; registra o que foi ligado."""
    linha = {"id_usuario": ID_USUARIO, "email": "joana@exemplo.com"}
    estado = {"linha": linha, "email_usado": False}
    ligados: list[tuple] = []
    monkeypatch.setattr(
        repositorio, "cliente_pendente", lambda _c, _cpf, travar=False: estado["linha"]
    )
    monkeypatch.setattr(
        repositorio, "email_em_uso_por_outro", lambda *_a: estado["email_usado"]
    )

    def ligar(_c, id_usuario, id_auth, email):
        ligados.append((id_usuario, id_auth, email))
        return estado.get("ligar", True)

    monkeypatch.setattr(repositorio, "ligar_login", ligar)
    estado["ligados"] = ligados
    return estado


# ------------------------------------------------------------------ servico


def test_mascara_o_email():
    assert service.mascarar_email("joana@exemplo.com") == "j***@exemplo.com"


def test_consulta_nao_pede_email_quando_o_cadastro_tem(banco):
    assert service.consultar(ConexaoFalsa(), CPF) == {"pede_email": False}


def test_consulta_pede_email_sem_email_sem_cadastro_ou_ja_ativo(banco):
    banco["linha"] = {"id_usuario": ID_USUARIO, "email": None}
    assert service.consultar(ConexaoFalsa(), CPF) == {"pede_email": True}
    banco["linha"] = None  # CPF inexistente ou conta ja ativa: a tela nao distingue
    assert service.consultar(ConexaoFalsa(), CPF) == {"pede_email": True}


def test_ativa_com_o_email_do_cadastro_e_ignora_o_enviado(banco):
    conexao, auth = ConexaoFalsa(), AuthFalso()
    r = service.ativar(conexao, auth, cpf=CPF, senha="senha1234", email="outro@x.com")
    assert r == {"email": "j***@exemplo.com"}
    assert auth.criados == [("joana@exemplo.com", "senha1234")]
    assert banco["ligados"] == [(ID_USUARIO, ID_AUTH, "joana@exemplo.com")]
    assert conexao.eventos == ["commit"]


def test_sem_email_no_cadastro_usa_o_informado_em_minusculas(banco):
    banco["linha"] = {"id_usuario": ID_USUARIO, "email": None}
    auth = ConexaoFalsa(), AuthFalso()
    r = service.ativar(auth[0], auth[1], cpf=CPF, senha="senha1234", email=" Ana@Exemplo.COM ")
    assert r == {"email": "a***@exemplo.com"}
    assert auth[1].criados == [("ana@exemplo.com", "senha1234")]
    assert banco["ligados"][0][2] == "ana@exemplo.com"


def test_sem_email_no_cadastro_e_sem_email_informado_pede_o_email(banco):
    banco["linha"] = {"id_usuario": ID_USUARIO, "email": None}
    auth = AuthFalso()
    with pytest.raises(EmailObrigatorio):
        service.ativar(ConexaoFalsa(), auth, cpf=CPF, senha="senha1234", email=None)
    assert auth.criados == []


def test_cpf_sem_cadastro_pedindo_email_nao_revela_nada(banco):
    banco["linha"] = None
    with pytest.raises(EmailObrigatorio):
        service.ativar(ConexaoFalsa(), AuthFalso(), cpf=CPF, senha="senha1234", email=None)
    with pytest.raises(AtivacaoNegada):
        service.ativar(ConexaoFalsa(), AuthFalso(), cpf=CPF, senha="senha1234", email="a@b.co")


def test_email_informado_em_uso_por_outro_cliente_e_negado(banco):
    banco["linha"] = {"id_usuario": ID_USUARIO, "email": None}
    banco["email_usado"] = True
    auth = AuthFalso()
    with pytest.raises(AtivacaoNegada):
        service.ativar(ConexaoFalsa(), auth, cpf=CPF, senha="senha1234", email="ana@exemplo.com")
    assert auth.criados == []


def test_email_que_o_auth_ja_tem_vira_negado_e_desfaz(banco):
    conexao = ConexaoFalsa()
    with pytest.raises(AtivacaoNegada):
        service.ativar(
            conexao, AuthFalso(erro=EmailJaNoAuth()), cpf=CPF, senha="senha1234", email=None
        )
    assert conexao.eventos == ["rollback"]
    assert banco["ligados"] == []


def test_corrida_na_ligacao_apaga_a_conta_criada(banco):
    banco["ligar"] = False
    conexao, auth = ConexaoFalsa(), AuthFalso()
    with pytest.raises(AtivacaoNegada):
        service.ativar(conexao, auth, cpf=CPF, senha="senha1234", email=None)
    assert auth.apagados == [ID_AUTH]
    assert "commit" not in conexao.eventos


def test_falha_do_banco_depois_do_auth_apaga_a_conta_criada(banco, monkeypatch):
    def quebra(*_a):
        raise RuntimeError("banco caiu")

    monkeypatch.setattr(repositorio, "ligar_login", quebra)
    conexao, auth = ConexaoFalsa(), AuthFalso()
    with pytest.raises(RuntimeError):
        service.ativar(conexao, auth, cpf=CPF, senha="senha1234", email=None)
    assert auth.apagados == [ID_AUTH]
    assert conexao.eventos == ["rollback"]


# ------------------------------------------------------------ Admin API (httpx)


def _admin(manipulador):
    cliente = httpx.Client(transport=httpx.MockTransport(manipulador))
    return AuthAdminSupabase("https://proj.supabase.co", "chave-de-teste", cliente=cliente)


def test_admin_cria_usuario_confirmado_com_a_chave_no_cabecalho():
    visto = {}

    def manipulador(req: httpx.Request) -> httpx.Response:
        visto["url"], visto["auth"] = str(req.url), req.headers["authorization"]
        visto["corpo"] = req.content.decode()
        return httpx.Response(200, json={"id": str(ID_AUTH)})

    assert _admin(manipulador).criar_usuario("a@b.co", "senha1234") == ID_AUTH
    assert visto["url"] == "https://proj.supabase.co/auth/v1/admin/users"
    assert visto["auth"] == "Bearer chave-de-teste"
    assert '"email_confirm":true' in visto["corpo"].replace(" ", "")


@pytest.mark.parametrize(
    ("corpo", "esperado"),
    [
        ({"error_code": "email_exists"}, EmailJaNoAuth),
        ({"error_code": "weak_password"}, SenhaRecusada),
        ({"error_code": "unexpected_failure"}, AtivacaoIndisponivel),
    ],
)
def test_admin_traduz_os_erros_do_auth(corpo, esperado):
    admin = _admin(lambda _r: httpx.Response(422, json=corpo))
    with pytest.raises(esperado):
        admin.criar_usuario("a@b.co", "senha1234")


def test_admin_fora_do_ar_vira_indisponivel():
    def cai(_r):
        raise httpx.ConnectError("sem rede")

    with pytest.raises(AtivacaoIndisponivel):
        _admin(cai).criar_usuario("a@b.co", "senha1234")


def test_admin_apagar_nao_levanta_mesmo_com_falha():
    _admin(lambda _r: httpx.Response(500)).apagar_usuario(ID_AUTH)


# ----------------------------------------------------------------------- HTTP


@pytest.fixture
def http(banco):
    conexao, auth = ConexaoFalsa(), AuthFalso()
    app = criar_app(
        Settings(
            _env_file=None,
            database_url=DATABASE_URL_TESTE,
            supabase_url="https://proj.supabase.co",
            supabase_service_role_key="chave-de-teste",
        )
    )
    app.dependency_overrides[get_executar] = lambda: (lambda operacao: operacao(conexao))
    app.dependency_overrides[get_auth_admin] = lambda: auth
    cliente = TestClient(app, raise_server_exceptions=False)
    cliente.auth_falso, cliente.conexao = auth, conexao
    return cliente


def test_rotas_publicas_respondem_sem_token(http):
    r = http.post("/api/v1/ativacao-conta/consultar", json={"cpf": "529.982.247-25"})
    assert r.status_code == 200
    assert r.json() == {"pede_email": False}
    r = http.post("/api/v1/ativacao-conta", json={"cpf": CPF, "senha": "senha1234"})
    assert r.status_code == 200
    assert r.json() == {"email": "j***@exemplo.com"}
    assert http.auth_falso.criados == [("joana@exemplo.com", "senha1234")]


@pytest.mark.parametrize(
    "corpo",
    [
        {"cpf": "123", "senha": "senha1234"},
        {"cpf": CPF, "senha": "curta1"},
        {"cpf": CPF, "senha": "somenteletras"},
        {"cpf": CPF, "senha": "12345678"},
        {"cpf": CPF, "senha": "senha1234", "email": "nao-e-email"},
        {"cpf": CPF, "senha": "senha1234", "papel": "admin"},
        {"cpf": CPF, "senha": "senha1234", "auth_user_id": str(uuid4())},
    ],
)
def test_entrada_invalida_e_422_e_nao_toca_no_auth(http, corpo):
    assert http.post("/api/v1/ativacao-conta", json=corpo).status_code == 422
    assert http.auth_falso.criados == []


def test_negada_responde_409_com_texto_unico(http, banco):
    banco["linha"] = None
    corpo = {"cpf": CPF, "senha": "senha1234", "email": "a@b.co"}
    r = http.post("/api/v1/ativacao-conta", json=corpo)
    assert r.status_code == 409
    assert "procure uma loja" in r.json()["detail"]


def test_sem_chave_do_servico_responde_503_sem_vazar_nada():
    app = criar_app(
        Settings(
            _env_file=None, database_url=DATABASE_URL_TESTE, supabase_url="https://p.supabase.co"
        )
    )
    r = TestClient(app, raise_server_exceptions=False).post(
        "/api/v1/ativacao-conta", json={"cpf": CPF, "senha": "senha1234"}
    )
    assert r.status_code == 503


def test_limite_de_ip_barra_a_tentativa_em_massa(banco):
    app = criar_app(
        Settings(
            _env_file=None,
            database_url=DATABASE_URL_TESTE,
            limites_ativos=True,
            limite_sensivel_por_minuto=3,
        )
    )
    conexao = ConexaoFalsa()
    app.dependency_overrides[get_executar] = lambda: (lambda operacao: operacao(conexao))
    cliente = TestClient(app)
    codigos = [
        cliente.post("/api/v1/ativacao-conta/consultar", json={"cpf": CPF}).status_code
        for _ in range(5)
    ]
    assert codigos == [200, 200, 200, 429, 429]
