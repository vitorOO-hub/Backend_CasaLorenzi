from uuid import uuid4

import pytest

from app.assistente import ferramentas, provedor, service
from app.assistente.roteamento import DestinoModelo
from app.core.config import Settings
from app.core.papeis import Papel, UsuarioAtual


def test_diagnostico_http_omite_chave_e_limita_mensagem():
    chave = "AIzaabcdefghijklmnopqrstuvwxyz0123456789"
    resposta = provedor.httpx.Response(
        400,
        json={
            "error": {
                "status": "INVALID_ARGUMENT",
                "message": f"Schema inválido para a chave {chave} {'x' * 600}",
            }
        },
    )

    status, mensagem = provedor._detalhe_http_seguro(resposta, chave)

    assert status == "INVALID_ARGUMENT"
    assert chave not in mensagem
    assert "[chave omitida]" in mensagem
    assert len(mensagem) == 500


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
                {
                    "content": {
                        "parts": [
                            {
                                "functionCall": {
                                    "name": "consultar_equipe",
                                    "args": {},
                                },
                                "thoughtSignature": "assinatura-teste",
                            }
                        ]
                    }
                }
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

    timeout_recebido = {}

    def criar_cliente(**kwargs):
        timeout_recebido.update(kwargs)
        return ClienteFalso()

    monkeypatch.setattr(provedor.httpx, "Client", criar_cliente)
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
    timeout_esperado = (
        provedor.TIMEOUT_GEMINI_SEGUNDOS
        if provedor_nome == "gemini"
        else provedor.TIMEOUT_GROQ_SEGUNDOS
    )
    assert timeout_recebido["timeout"] == timeout_esperado
    if provedor_nome == "gemini":
        assert turno["chamadas"][0]["thought_signature"] == "assinatura-teste"
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


def test_historico_gemini_preserva_assinatura_de_pensamento():
    historico = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-1",
                    "name": "consultar_vendas",
                    "arguments": {"inicio": "2025-01-01", "fim": "2025-12-31"},
                    "thought_signature": "assinatura-teste",
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call-1",
            "name": "consultar_vendas",
            "content": '{"atual": {"faturamento": 100}}',
        },
    ]

    assert provedor._historico_gemini(historico) == [
        {
            "role": "model",
            "parts": [
                {
                    "functionCall": {
                        "name": "consultar_vendas",
                        "args": {"inicio": "2025-01-01", "fim": "2025-12-31"},
                    },
                    "thoughtSignature": "assinatura-teste",
                }
            ],
        },
        {
            "role": "user",
            "parts": [
                {
                    "functionResponse": {
                        "name": "consultar_vendas",
                        "response": {"atual": {"faturamento": 100}},
                    }
                }
            ],
        },
    ]


def test_tools_gemini_envia_esquema_json_no_campo_compativel():
    esquema = {
        "type": "object",
        "properties": {"busca": {"type": "string"}},
        "required": ["busca"],
        "additionalProperties": False,
    }

    ferramentas_gemini = provedor._tools_gemini(
        [{"name": "buscar_cliente", "description": "Busca cliente", "parameters": esquema}]
    )

    funcao = ferramentas_gemini[0]["functionDeclarations"][0]
    assert funcao["parametersJsonSchema"] == esquema
    assert "parameters" not in funcao


def _configuracoes_assistente() -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql://localhost/teste",
        groq_api_key="chave-groq-falsa",
        gemini_api_key="chave-gemini-falsa",
    )


def _preparar_persistencia(monkeypatch):
    monkeypatch.setattr(service.repositorio, "id_usuario_ativo", lambda *_args: uuid4())
    monkeypatch.setattr(service.repositorio, "gravar_pergunta", lambda *_args: [])
    monkeypatch.setattr(service.repositorio, "gravar_resposta", lambda *_args: None)
    monkeypatch.setattr(service.repositorio, "marcar_pergunta_sem_resposta", lambda *_args: None)
    monkeypatch.setattr(service.repositorio, "gravar_ferramenta", lambda *_args: None)


def _executar_db(callback):
    return callback(None)


def test_encaminha_para_area_responsavel_sem_inventar_nome():
    mensagem = service.mensagem_sem_confirmacao(
        "Qual é o estoque da peça X?", "a consulta não encontrou registros."
    )

    assert "Não posso confirmar" in mensagem
    assert "responsável pelo estoque" in mensagem
    assert "gerente da unidade" in mensagem


def test_falta_de_evidencia_de_catalogo_encaminha_para_administrador_do_catalogo():
    mensagem = service.mensagem_sem_confirmacao(
        "Quais produtos indexados são de linho?", "a consulta não encontrou registros."
    )

    assert "administrador responsável pelo catálogo" in mensagem


def test_pergunta_de_dado_sem_chamada_de_ferramenta_abstem(monkeypatch):
    _preparar_persistencia(monkeypatch)
    monkeypatch.setattr(
        provedor,
        "completar",
        lambda *_args: {
            "texto": "Temos 42 unidades em estoque.",
            "chamadas": [],
            "tokens_entrada": 1,
            "tokens_saida": 2,
        },
    )

    resposta = service.enviar_mensagem(
        _executar_db,
        admin(),
        _configuracoes_assistente(),
        uuid4(),
        "Quantas unidades temos no estoque?",
    )

    assert "Não posso confirmar" in resposta["resposta"]
    assert "responsável pelo estoque" in resposta["resposta"]
    assert "42" not in resposta["resposta"]


def test_falha_na_consulta_abstem_sem_pedir_nova_resposta_ao_modelo(monkeypatch):
    _preparar_persistencia(monkeypatch)
    chamadas_modelo = 0

    def completar(*_args):
        nonlocal chamadas_modelo
        chamadas_modelo += 1
        return {
            "texto": "",
            "chamadas": [
                {
                    "id": "call-1",
                    "name": "consultar_estoque",
                    "arguments": {"sku": "CAM-001"},
                }
            ],
            "tokens_entrada": 1,
            "tokens_saida": 1,
        }

    monkeypatch.setattr(provedor, "completar", completar)
    monkeypatch.setattr(
        ferramentas,
        "executar",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("banco indisponível")),
    )

    resposta = service.enviar_mensagem(
        _executar_db,
        admin(),
        _configuracoes_assistente(),
        uuid4(),
        "Tem estoque da peça CAM-001 na loja Savassi?",
    )

    assert chamadas_modelo == 1
    assert "Não posso confirmar" in resposta["resposta"]
    assert "responsável pelo estoque" in resposta["resposta"]


def test_consulta_sem_registros_abstem_sem_gerar_resposta_livre(monkeypatch):
    _preparar_persistencia(monkeypatch)
    chamadas_modelo = 0

    def completar(*_args):
        nonlocal chamadas_modelo
        chamadas_modelo += 1
        return {
            "texto": "",
            "chamadas": [
                {
                    "id": "call-1",
                    "name": "consultar_estoque",
                    "arguments": {"sku": "CAM-001"},
                }
            ],
            "tokens_entrada": 1,
            "tokens_saida": 1,
        }

    monkeypatch.setattr(provedor, "completar", completar)
    monkeypatch.setattr(ferramentas, "executar", lambda *_args: {"itens": [], "total": 0})

    resposta = service.enviar_mensagem(
        _executar_db,
        admin(),
        _configuracoes_assistente(),
        uuid4(),
        "Tem estoque da peça CAM-001 na loja Savassi?",
    )

    assert chamadas_modelo == 1
    assert "Não posso confirmar" in resposta["resposta"]
    assert "não encontrou registros" in resposta["resposta"]
    assert "responsável pelo estoque" in resposta["resposta"]
