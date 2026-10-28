from uuid import uuid4

import pytest

from app.assistente import ferramentas, provedor
from app.assistente.roteamento import DestinoModelo
from app.core.config import Settings
from app.core.papeis import Papel, UsuarioAtual


def admin() -> UsuarioAtual:
    return UsuarioAtual(id_auth=uuid4(), papel=Papel.ADMIN)


def test_ferramenta_nao_aceita_consulta_sql_arbitraria():
    with pytest.raises(ferramentas.FerramentaInvalida):
        ferramentas.executar(None, admin(), "executar_sql", {"sql": "select * from usuario"})


def test_ferramenta_exige_admin_antes_de_acessar_dados():
    usuario = UsuarioAtual(id_auth=uuid4(), papel=Papel.GERENTE_LOJA, id_loja=uuid4())
    with pytest.raises(ferramentas.FerramentaInvalida, match="administrador"):
        ferramentas.executar(None, usuario, "consultar_equipe", {})


def test_ferramenta_rejeita_argumento_extra():
    with pytest.raises(ferramentas.FerramentaInvalida, match="Argumentos inválidos"):
        ferramentas.executar(
            None,
            admin(),
            "consultar_equipe",
            {"cargo": "admin", "alterar_cargo": True},
        )


def test_consulta_de_vendas_limita_periodo_antes_do_banco():
    with pytest.raises(ferramentas.FerramentaInvalida, match="até 367 dias"):
        ferramentas.executar(
            None,
            admin(),
            "consultar_vendas",
            {"inicio": "2024-01-01", "fim": "2026-01-01"},
        )


@pytest.mark.parametrize("provedor_nome", ["groq", "gemini"])
def test_adaptador_converte_chamada_de_ferramenta_sem_rede(provedor_nome, monkeypatch):
    if provedor_nome == "groq":
        resposta = {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "function": {
                                    "name": "consultar_equipe",
                                    "arguments": "{}",
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2},
        }
    else:
        resposta = {
            "candidates": [
                {"content": {"parts": [{"functionCall": {"name": "consultar_equipe", "args": {}}}]}}
            ],
            "usageMetadata": {"promptTokenCount": 9, "candidatesTokenCount": 3},
        }

    class RespostaFalsa:
        def raise_for_status(self):
            return None

        def json(self):
            return resposta

    class ClienteFalso:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, *_args, **_kwargs):
            return RespostaFalsa()

    monkeypatch.setattr(provedor.httpx, "Client", lambda **_kwargs: ClienteFalso())
    settings = Settings(
        _env_file=None,
        database_url="postgresql://localhost/teste",
        groq_api_key="chave-groq-falsa",
        gemini_api_key="chave-gemini-falsa",
    )
    turno = provedor.completar(
        DestinoModelo(provedor=provedor_nome, modelo="modelo-teste"),
        settings,
        "instrucoes",
        [{"role": "user", "content": "Quem faz parte da equipe?"}],
        ferramentas.FERRAMENTAS,
    )

    assert turno["chamadas"][0]["name"] == "consultar_equipe"
    assert turno["chamadas"][0]["arguments"] == {}
    assert turno["tokens_entrada"] > 0


def test_historico_groq_formata_corretamente_o_retorno_de_ferramenta():
    historico = [
        {"role": "user", "content": "Quantas lojas existem?"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-1",
                    "name": "consultar_lojas",
                    "arguments": {"regiao": "todas"},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call-1",
            "name": "consultar_lojas",
            "content": '{"total": 4}',
        },
    ]

    assert provedor._historico_groq(historico) == [
        {"role": "user", "content": "Quantas lojas existem?"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": "consultar_lojas",
                        "arguments": '{"regiao": "todas"}',
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call-1", "content": '{"total": 4}'},
    ]
