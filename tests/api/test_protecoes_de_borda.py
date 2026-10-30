"""Protecoes de borda: limite de requisicoes, cabecalhos, docs fechadas e erros sem vazamento."""

import gzip

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.gzip import GZipMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.core.config import Settings
from app.core.erros import registrar_tratadores
from app.core.protecoes import CabecalhosDeSeguranca, LimitadorDeRequisicoes
from app.main import criar_app
from tests.conftest import DATABASE_URL_TESTE


class Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nome: str = Field(min_length=3)
    quantidade: int = Field(gt=0)


def app_de_teste(**limites) -> TestClient:
    app = FastAPI()
    registrar_tratadores(app)
    app.add_middleware(LimitadorDeRequisicoes, **limites)
    app.add_middleware(CabecalhosDeSeguranca)

    @app.get("/ler")
    def ler():
        return {"ok": True}

    @app.post("/escrever")
    def escrever(dados: Entrada):
        return {"ok": True}

    @app.post("/api/v1/cliente/pedidos")
    def pedido():
        return {"ok": True}

    @app.get("/health")
    def saude():
        return {"ok": True}

    @app.get("/quebra")
    def quebra():
        raise RuntimeError("segredo-interno postgresql://usuario:senha@host/banco")

    # Como em producao (uvicorn --proxy-headers --forwarded-allow-ips='*'): o uvicorn reescreve o
    # IP da conexao com o primeiro item do X-Forwarded-For, que o cliente escolhe.
    return TestClient(ProxyHeadersMiddleware(app, trusted_hosts="*"), raise_server_exceptions=False)


def do_ip(ip: str, **extras: str) -> dict:
    """IP do cliente como a Cloudflare entrega ao app (CF-Connecting-IP)."""
    return {"CF-Connecting-IP": ip, **extras}


def com_token(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ------------------------------------------------------------------ limite de requisicoes


def test_leitura_passa_do_limite_e_recebe_429_com_retry_after():
    cliente = app_de_teste(leitura=3, escrita=30, sensivel=10)
    cab = do_ip("10.0.0.1")
    assert [cliente.get("/ler", headers=cab).status_code for _ in range(3)] == [200, 200, 200]
    resposta = cliente.get("/ler", headers=cab)
    assert resposta.status_code == 429
    assert int(resposta.headers["retry-after"]) >= 1
    assert "Aguarde" in resposta.json()["detail"]


def test_cada_ip_tem_o_proprio_limite_e_leitura_nao_gasta_o_de_escrita():
    cliente = app_de_teste(leitura=1, escrita=2, sensivel=1)
    assert cliente.get("/ler", headers=do_ip("10.0.0.1")).status_code == 200
    assert cliente.get("/ler", headers=do_ip("10.0.0.1")).status_code == 429
    assert cliente.get("/ler", headers=do_ip("10.0.0.2")).status_code == 200  # outro IP
    corpo = {"nome": "abc", "quantidade": 1}
    assert cliente.post("/escrever", json=corpo, headers=do_ip("10.0.0.1")).status_code == 200


def test_o_token_nao_entra_na_chave_trocar_ou_omitir_o_token_nao_zera_o_limite():
    cliente = app_de_teste(leitura=2, escrita=100, sensivel=100)
    assert cliente.get("/ler", headers=do_ip("10.0.0.1", **com_token("a"))).status_code == 200
    assert cliente.get("/ler", headers=do_ip("10.0.0.1", **com_token("b"))).status_code == 200
    assert cliente.get("/ler", headers=do_ip("10.0.0.1", **com_token("c"))).status_code == 429
    assert cliente.get("/ler", headers=do_ip("10.0.0.1")).status_code == 429  # sem token
    # O mesmo token vindo de outro IP tem contador proprio.
    assert cliente.get("/ler", headers=do_ip("10.0.0.2", **com_token("a"))).status_code == 200


def test_x_forwarded_for_forjado_nao_burla_o_limite():
    cliente = app_de_teste(leitura=2, escrita=100, sensivel=100)
    codigos = [
        cliente.get(
            "/ler", headers=do_ip("10.0.0.1", **{"X-Forwarded-For": f"9.9.9.{i}"})
        ).status_code
        for i in range(5)
    ]
    assert codigos == [200, 200, 429, 429, 429]


def test_sem_cabecalho_da_cloudflare_ou_com_valor_invalido_usa_o_ip_da_conexao():
    cliente = app_de_teste(leitura=1, escrita=100, sensivel=100)
    assert cliente.get("/ler", headers={"CF-Connecting-IP": "isso-nao-e-ip"}).status_code == 200
    assert cliente.get("/ler").status_code == 429  # mesmo balde: o da conexao
    assert cliente.get("/ler", headers=do_ip("10.0.0.7")).status_code == 200  # IP valido: outro


def test_escrita_sensivel_tem_limite_proprio_mais_baixo():
    cliente = app_de_teste(leitura=100, escrita=100, sensivel=2)
    cab = do_ip("10.0.0.1")
    assert cliente.post("/api/v1/cliente/pedidos", headers=cab).status_code == 200
    assert cliente.post("/api/v1/cliente/pedidos", headers=cab).status_code == 200
    assert cliente.post("/api/v1/cliente/pedidos", headers=cab).status_code == 429


def test_saude_e_preflight_ficam_de_fora_do_limite():
    cliente = app_de_teste(leitura=1, escrita=1, sensivel=1)
    cab = do_ip("10.0.0.1")
    assert cliente.get("/ler", headers=cab).status_code == 200
    assert cliente.get("/ler", headers=cab).status_code == 429
    assert all(cliente.get("/health", headers=cab).status_code == 200 for _ in range(10))
    assert all(cliente.options("/ler", headers=cab).status_code != 429 for _ in range(10))


def test_limite_libera_depois_da_janela():
    agora = [1000.0]
    app = FastAPI()
    app.add_middleware(LimitadorDeRequisicoes, leitura=1, relogio=lambda: agora[0])

    @app.get("/ler")
    def ler():
        return {}

    cliente = TestClient(app)
    assert cliente.get("/ler").status_code == 200
    assert cliente.get("/ler").status_code == 429
    agora[0] += 61
    assert cliente.get("/ler").status_code == 200


# ------------------------------------------------------------------ cabecalhos e erros


def test_cabecalhos_de_seguranca_em_toda_resposta_inclusive_429():
    cliente = app_de_teste(leitura=1)
    for _ in range(2):
        r = cliente.get("/ler")
    assert r.status_code == 429
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["cache-control"] == "no-store"


def test_erro_inesperado_nao_vaza_nada_interno():
    cliente = app_de_teste()
    resposta = cliente.get("/quebra")
    assert resposta.status_code == 500
    assert resposta.json() == {"detail": "Erro interno. Tente de novo em instantes."}
    assert "senha" not in resposta.text and "segredo" not in resposta.text


def test_422_vem_em_portugues_e_sem_ecoar_o_corpo_enviado():
    cliente = app_de_teste()
    r = cliente.post("/escrever", json={"nome": "a", "quantidade": 0, "intruso": "SENHA123"})
    assert r.status_code == 422
    corpo = r.json()
    assert "SENHA123" not in r.text
    campos = {c["campo"]: c["mensagem"] for c in corpo["campos"]}
    assert campos["nome"] == "Texto curto demais"
    assert campos["quantidade"] == "Valor menor do que o permitido"
    assert campos["intruso"] == "Campo nao permitido"
    assert corpo["detail"].startswith("Dados invalidos")


def test_rota_inexistente_responde_em_portugues():
    r = app_de_teste().get("/nao-existe")
    assert r.status_code == 404 and r.json() == {"detail": "Rota nao encontrada"}


# ------------------------------------------------------------------ app de verdade


def test_docs_e_openapi_ficam_fechados_por_padrao_e_abrem_so_de_proposito():
    fechado = TestClient(criar_app(Settings(_env_file=None, database_url=DATABASE_URL_TESTE)))
    for caminho in ("/docs", "/redoc", "/openapi.json"):
        assert fechado.get(caminho).status_code == 404
    aberto = TestClient(
        criar_app(Settings(_env_file=None, database_url=DATABASE_URL_TESTE, docs_habilitadas=True))
    )
    assert aberto.get("/openapi.json").status_code == 200


def test_app_aplica_limite_cabecalhos_e_cors_juntos():
    settings = Settings(
        _env_file=None,
        database_url=DATABASE_URL_TESTE,
        cors_origins=["http://localhost:5173"],
        limites_ativos=True,
        limite_leitura_por_minuto=1,
    )
    cliente = TestClient(criar_app(settings))
    cab = {"Origin": "http://localhost:5173"}
    rota = "/api/v1/painel/gerencia/pendencias"  # sem token e sem banco: nunca chega nele
    assert cliente.get(rota, headers=cab).status_code != 429
    r = cliente.get(rota, headers=cab)
    assert r.status_code == 429
    assert (
        r.headers["access-control-allow-origin"] == "http://localhost:5173"
    )  # o 429 chega ao front
    assert r.headers["x-content-type-options"] == "nosniff"


def test_cors_aceita_urls_de_branch_e_de_deploy_do_projeto_na_vercel_e_so_elas():
    cliente = TestClient(
        criar_app(
            Settings(
                _env_file=None,
                database_url=DATABASE_URL_TESTE,
                cors_origins=["https://projetocasalorenzi.vercel.app"],
            )
        )
    )

    def preflight(origem: str):
        return cliente.options(
            "/api/v1/cliente/chamados",
            headers={
                "Origin": origem,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )

    for ok in (
        "https://projetocasalorenzi.vercel.app",
        "https://projetocasalorenzi-git-main-vitor-s-projectss.vercel.app",
        "https://projetocasalorenzi-jdz8cvb2c-vitor-s-projectss.vercel.app",
    ):
        assert preflight(ok).headers["access-control-allow-origin"] == ok
    for nao in (
        "https://projetocasalorenzi-git-main-outro-time.vercel.app",
        "https://projetocasalorenzi.vercel.app.evil.com",
        "https://evil.vercel.app",
    ):
        assert preflight(nao).status_code == 400


def test_app_comprime_respostas_grandes_quando_cliente_aceita_gzip():
    app = criar_app(Settings(_env_file=None, database_url=DATABASE_URL_TESTE))
    assert any(middleware.cls is GZipMiddleware for middleware in app.user_middleware)

    corpo = b"x" * 1000
    mensagens = []

    async def aplicacao(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": corpo, "more_body": False})

    async def receber():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def enviar(mensagem):
        mensagens.append(mensagem)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/resposta-grande",
        "raw_path": b"/resposta-grande",
        "query_string": b"",
        "headers": [(b"accept-encoding", b"gzip")],
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
        "root_path": "",
    }

    # O caminho nao faz I/O; avancar a coroutine evita o socketpair do loop padrao do Windows.
    chamada = GZipMiddleware(aplicacao, minimum_size=500)(scope, receber, enviar)
    try:
        chamada.send(None)
    except StopIteration:
        pass
    else:
        pytest.fail("O middleware de compressao aguardou uma operacao externa inesperada")

    inicio = mensagens[0]
    cabecalhos = dict(inicio["headers"])
    assert inicio["status"] == 200
    assert cabecalhos[b"content-encoding"] == b"gzip"
    assert gzip.decompress(mensagens[-1]["body"]) == corpo


@pytest.mark.parametrize("variavel", ["LIMITES_ATIVOS"])
def test_testes_rodam_com_o_limite_desligado_por_padrao(variavel):
    assert Settings(_env_file=None, database_url=DATABASE_URL_TESTE).limites_ativos is False
