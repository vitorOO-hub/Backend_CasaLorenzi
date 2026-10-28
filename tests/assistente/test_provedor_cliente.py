"""Provedores Groq e Gemini com HTTP falso (httpx.MockTransport): nenhuma chamada real sai daqui."""

import json

import httpx
import pytest

from app.assistente.cliente import provedor as provedor_modulo
from app.assistente.cliente.provedor import (
    ErroProvedor,
    Ferramenta,
    ProvedorGemini,
    ProvedorGroq,
    criar_provedor,
)
from app.assistente.roteamento import DestinoModelo
from app.core.config import Settings
from tests.conftest import DATABASE_URL_TESTE

CHAVE = "chave-secreta-de-teste"
FERRAMENTAS = [
    Ferramenta(
        "consultar_pontos",
        "Saldo de pontos",
        {"type": "object", "properties": {"x": {"type": "string"}}, "additionalProperties": False},
    )
]
HISTORICO = [{"papel": "usuario", "texto": "quantos pontos eu tenho?"}]


def _cliente(respostas, pedidos):
    """Devolve as respostas em ordem e guarda cada requisicao feita."""
    fila = list(respostas)

    def tratar(requisicao: httpx.Request) -> httpx.Response:
        pedidos.append(requisicao)
        resposta = fila.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta

    return httpx.Client(transport=httpx.MockTransport(tratar))


def _responder(provedor, executar=None, max_rodadas=4):
    return provedor.responder(
        modelo="modelo-x",
        sistema="sistema",
        historico=HISTORICO,
        ferramentas=FERRAMENTAS,
        executar=executar or (lambda nome, args: {"saldo": 120}),
        max_rodadas=max_rodadas,
        max_tokens=600,
    )


def _groq_texto(texto, entrada=10, saida=5):
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"role": "assistant", "content": texto}}],
            "usage": {"prompt_tokens": entrada, "completion_tokens": saida},
        },
    )


def _groq_ferramenta(nome="consultar_pontos", argumentos="{}"):
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "c1",
                                "type": "function",
                                "function": {"name": nome, "arguments": argumentos},
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 20, "completion_tokens": 3},
        },
    )


@pytest.fixture(autouse=True)
def _sem_espera_real(monkeypatch):
    monkeypatch.setattr(provedor_modulo, "_dormir", lambda segundos: None)


def _sem_chave(requisicao: httpx.Request) -> None:
    assert CHAVE not in str(requisicao.url)
    assert CHAVE not in requisicao.content.decode()


# ------------------------------------------------------------------ Groq


def test_groq_responde_texto_com_chave_so_no_cabecalho():
    pedidos = []
    provedor = ProvedorGroq(CHAVE, _cliente([_groq_texto("Oi!")], pedidos))
    resposta = _responder(provedor)
    assert resposta.texto == "Oi!"
    assert (resposta.tokens_entrada, resposta.tokens_saida) == (10, 5)
    assert resposta.concluida and resposta.chamadas == []
    (requisicao,) = pedidos
    assert requisicao.headers["Authorization"] == f"Bearer {CHAVE}"
    _sem_chave(requisicao)
    corpo = json.loads(requisicao.content)
    assert corpo["model"] == "modelo-x"
    assert corpo["max_tokens"] == 600
    assert corpo["messages"][0] == {"role": "system", "content": "sistema"}
    assert corpo["tools"][0]["function"]["name"] == "consultar_pontos"


def test_groq_executa_a_ferramenta_e_devolve_o_resultado_ao_modelo():
    pedidos, executadas = [], []

    def executar(nome, argumentos):
        executadas.append((nome, argumentos))
        return {"saldo": 120}

    provedor = ProvedorGroq(
        CHAVE,
        _cliente(
            [_groq_ferramenta(argumentos='{"x": "1"}'), _groq_texto("Voce tem 120 pontos.")],
            pedidos,
        ),
    )
    resposta = _responder(provedor, executar)
    assert executadas == [("consultar_pontos", {"x": "1"})]
    assert resposta.texto == "Voce tem 120 pontos."
    assert [c.nome for c in resposta.chamadas] == ["consultar_pontos"]
    assert (resposta.tokens_entrada, resposta.tokens_saida) == (30, 8)
    segunda = json.loads(pedidos[1].content)["messages"]
    assert segunda[-1] == {"role": "tool", "tool_call_id": "c1", "content": '{"saldo": 120}'}


def test_groq_argumentos_ilegiveis_viram_dict_vazio():
    executadas = []
    provedor = ProvedorGroq(
        CHAVE, _cliente([_groq_ferramenta(argumentos="nao-e-json"), _groq_texto("ok")], [])
    )
    _responder(provedor, lambda n, a: executadas.append(a) or {})
    assert executadas == [{}]


def test_groq_para_quando_passa_do_limite_de_rodadas():
    provedor = ProvedorGroq(CHAVE, _cliente([_groq_ferramenta(), _groq_ferramenta()], []))
    resposta = _responder(provedor, max_rodadas=1)
    assert not resposta.concluida
    assert len(resposta.chamadas) == 1


@pytest.mark.parametrize(
    ("resposta", "motivo", "status"),
    [
        (httpx.Response(500, text=f"erro interno {CHAVE}"), "resposta de erro do provedor", 500),
        (httpx.Response(429, json={"error": "limite"}), "resposta de erro do provedor", 429),
        (httpx.Response(200, text="<html>"), "resposta ilegivel", None),
        (httpx.ReadTimeout("lento"), "tempo esgotado", None),
        (httpx.ConnectError("sem rede"), "falha de conexao", None),
    ],
)
def test_groq_erro_vira_erro_provedor_sem_repetir_o_corpo(resposta, motivo, status):
    # Duas respostas iguais: o 429 tenta de novo uma vez antes de desistir.
    provedor = ProvedorGroq(CHAVE, _cliente([resposta, resposta], []))
    with pytest.raises(ErroProvedor) as erro:
        _responder(provedor)
    assert (erro.value.provedor, erro.value.motivo, erro.value.status) == ("groq", motivo, status)
    assert CHAVE not in str(erro.value)


# ------------------------------------------------------------------ Gemini


def _gemini(partes, entrada=7, saida=2):
    return httpx.Response(
        200,
        json={
            "candidates": [{"content": {"role": "model", "parts": partes}}],
            "usageMetadata": {"promptTokenCount": entrada, "candidatesTokenCount": saida},
        },
    )


def test_gemini_usa_cabecalho_converte_esquema_e_executa_ferramenta():
    pedidos, executadas = [], []

    def executar(nome, argumentos):
        executadas.append((nome, argumentos))
        return {"saldo": 50}

    provedor = ProvedorGemini(
        CHAVE,
        _cliente(
            [
                _gemini([{"functionCall": {"name": "consultar_pontos", "args": {"x": "a"}}}]),
                _gemini([{"text": "Voce tem 50 pontos."}]),
            ],
            pedidos,
        ),
    )
    resposta = _responder(provedor, executar)
    assert resposta.texto == "Voce tem 50 pontos."
    assert executadas == [("consultar_pontos", {"x": "a"})]
    assert (resposta.tokens_entrada, resposta.tokens_saida) == (14, 4)
    primeira = pedidos[0]
    assert primeira.headers["x-goog-api-key"] == CHAVE
    assert "key=" not in str(primeira.url)
    assert str(primeira.url).endswith("/models/modelo-x:generateContent")
    _sem_chave(primeira)
    corpo = json.loads(primeira.content)
    assert corpo["systemInstruction"] == {"parts": [{"text": "sistema"}]}
    assert corpo["generationConfig"]["maxOutputTokens"] == 600
    parametros = corpo["tools"][0]["functionDeclarations"][0]["parameters"]
    assert parametros == {"type": "OBJECT", "properties": {"x": {"type": "STRING"}}}
    retorno = json.loads(pedidos[1].content)["contents"][-1]
    assert retorno["parts"][0]["functionResponse"] == {
        "name": "consultar_pontos",
        "response": {"saldo": 50},
    }


def test_gemini_erro_http_vira_erro_provedor():
    provedor = ProvedorGemini(CHAVE, _cliente([httpx.Response(403, text=CHAVE)], []))
    with pytest.raises(ErroProvedor) as erro:
        _responder(provedor)
    assert (erro.value.provedor, erro.value.status) == ("gemini", 403)
    assert CHAVE not in str(erro.value)


# ------------------------------------------------------------------ fabrica


def _settings(**extras):
    return Settings(_env_file=None, database_url=DATABASE_URL_TESTE, **extras)


def test_criar_provedor_escolhe_pelo_destino_sem_fallback():
    configuracoes = _settings(groq_api_key="g", gemini_api_key="m")
    assert isinstance(criar_provedor(DestinoModelo("groq", "a"), configuracoes), ProvedorGroq)
    assert isinstance(criar_provedor(DestinoModelo("gemini", "b"), configuracoes), ProvedorGemini)


def test_criar_provedor_sem_a_chave_do_destino_recusa_em_vez_de_trocar():
    with pytest.raises(ErroProvedor, match="chave ausente"):
        criar_provedor(DestinoModelo("gemini", "b"), _settings(groq_api_key="g"))


# ------------------------------------------------------------------ limite por minuto (429)


def test_429_com_espera_curta_espera_e_tenta_de_novo(monkeypatch):
    esperas = []
    monkeypatch.setattr(provedor_modulo, "_dormir", esperas.append)
    pedidos = []
    limite = httpx.Response(
        429, headers={"retry-after": "2"}, json={"error": {"code": "rate_limit_exceeded"}}
    )
    resposta = _responder(ProvedorGroq(CHAVE, _cliente([limite, _groq_texto("Oi!")], pedidos)))
    assert resposta.texto == "Oi!" and esperas == [2.0] and len(pedidos) == 2


def test_429_que_persiste_vira_erro_de_limite_com_o_codigo(monkeypatch):
    monkeypatch.setattr(provedor_modulo, "_dormir", lambda s: None)
    limite = httpx.Response(
        429, json={"error": {"code": "rate_limit_exceeded", "message": f"org {CHAVE}"}}
    )
    with pytest.raises(ErroProvedor) as erro:
        _responder(ProvedorGroq(CHAVE, _cliente([limite, limite], [])))
    assert erro.value.limite_de_uso and erro.value.codigo == "rate_limit_exceeded"
    assert CHAVE not in str(erro.value)


def test_429_com_espera_longa_nao_segura_o_cliente(monkeypatch):
    esperas = []
    monkeypatch.setattr(provedor_modulo, "_dormir", esperas.append)
    limite = httpx.Response(429, headers={"retry-after": "40"}, json={})
    with pytest.raises(ErroProvedor):
        _responder(ProvedorGroq(CHAVE, _cliente([limite], [])))
    assert esperas == []


def test_codigo_do_erro_400_fica_registrado_sem_a_mensagem():
    falha = httpx.Response(
        400, json={"error": {"code": "tool_use_failed", "message": "geracao falhou"}}
    )
    with pytest.raises(ErroProvedor) as erro:
        _responder(ProvedorGroq(CHAVE, _cliente([falha], [])))
    assert erro.value.codigo == "tool_use_failed" and "geracao" not in str(erro.value)


def test_espera_pedida_pelo_provedor_fica_no_erro():
    limite = httpx.Response(
        429, headers={"retry-after": "305"}, json={"error": {"code": "rate_limit_exceeded"}}
    )
    with pytest.raises(ErroProvedor) as erro:
        _responder(ProvedorGroq(CHAVE, _cliente([limite], [])))
    assert erro.value.espera == 305.0
