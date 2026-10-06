def test_health(cliente):
    resposta = cliente.get("/health")
    assert resposta.status_code == 200
    assert resposta.json() == {"status": "ok"}


def test_cors_libera_origem_configurada(cliente):
    resposta = cliente.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert resposta.status_code == 200
    assert resposta.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_nega_origem_desconhecida(cliente):
    resposta = cliente.options(
        "/health",
        headers={
            "Origin": "https://site-malicioso.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resposta.status_code == 400
    assert "access-control-allow-origin" not in resposta.headers
