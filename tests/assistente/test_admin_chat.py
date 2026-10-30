from uuid import uuid4

import pytest

from app.assistente import admin as assistente_admin
from app.assistente import ferramentas, periodos, provedor, repositorio, service
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


def test_comparacao_de_lojas_e_exclusiva_do_admin(monkeypatch):
    chamadas = []
    lojas = [
        {"id_loja": uuid4(), "nome": f"Loja {i}", "faturamento": float(i),
         "faturamento_anterior": 0, "pedidos": i, "ticket_medio": 1}
        for i in range(21)
    ]

    def montar_rede(_c, usuario, **kwargs):
        chamadas.append((usuario, kwargs))
        return {"unidades": lojas, "periodo": {}, "periodo_anterior": {}}

    monkeypatch.setattr(ferramentas.gerencia_service, "montar_rede", montar_rede)
    argumentos = {"inicio": "2026-01-01", "fim": "2026-01-31"}
    resultado = ferramentas.executar(None, admin(), "comparar_vendas_lojas", argumentos)
    assert resultado["total_lojas"] == 21
    assert resultado["lojas_omitidas"] == 1
    assert resultado["lojas_maior_faturamento"][0]["faturamento"] == 20
    assert resultado["loja_menor_faturamento"]["faturamento"] == 0
    assert chamadas[0][1]["ids_loja"] == ()
    assert "aviso" not in service._json_para_modelo(resultado)[0]
    gerente = UsuarioAtual(id_auth=uuid4(), papel=Papel.GERENTE_LOJA, id_loja=uuid4())
    with pytest.raises(ferramentas.FerramentaInvalida):
        ferramentas.executar(None, gerente, "comparar_vendas_lojas", argumentos)


@pytest.mark.parametrize("detalhe", ["resumo", "pecas_mais_vendidas", "marcas"])
def test_vendas_admin_retorna_resumo_e_detalhe_solicitado(monkeypatch, detalhe):
    dashboard = {
        "periodo": {"inicio": "2026-01-01", "fim": "2026-10-30"},
        "atual": {"faturamento": 123},
        "anterior": {"faturamento": 100},
        "serie_diaria": [{"descricao": "x" * 100} for _ in range(365)],
        "opcoes": {"marcas": ["x" * 100 for _ in range(100)]},
        "pecas_mais_vendidas": [{"nome": "Camisa", "unidades": 4}],
        "marcas": [{"marca": "A", "faturamento": 123}],
    }
    monkeypatch.setattr(
        ferramentas.gerencia_service, "montar_dashboard", lambda *_a, **_k: dashboard
    )
    resultado = ferramentas.executar(
        None, admin(), "consultar_vendas",
        {"inicio": "2026-01-01", "fim": "2026-10-30", "detalhe": detalhe},
    )
    assert resultado["atual"]["faturamento"] == 123
    assert "opcoes" not in resultado
    assert "serie_diaria" not in resultado
    if detalhe != "resumo":
        assert resultado[detalhe] == dashboard[detalhe]
    assert "aviso" not in service._json_para_modelo(resultado)[0]


@pytest.mark.parametrize(
    ("pergunta", "resposta"),
    [
        ("qual a receita da rede?", "Qual período"),
        ("quanto ganhamos esse ano?", "faturamento ou o lucro"),
        ("qual o lucro da rede este ano?", "não consigo consultar o lucro"),
    ],
)
def test_admin_esclarece_vendas_e_lucro_sem_valores_inventados(pergunta, resposta):
    assert resposta in assistente_admin.esclarecimento_necessario(pergunta)


@pytest.mark.parametrize(
    "pergunta", ["Quais são os pedidos pendentes?", "Mostre as marcas do catálogo"]
)
def test_admin_nao_exige_periodo_em_consultas_que_nao_precisam(pergunta):
    assert assistente_admin.esclarecimento_necessario(pergunta) is None


@pytest.mark.parametrize(
    ("pergunta", "periodo"),
    [("qual a receita da rede?", "dos ultimos 30 dias"), ("faturamento", "este ano")],
)
def test_admin_recupera_periodo_preservando_visao_da_rede(pergunta, periodo):
    historico = [
        {"role": "user", "content": pergunta},
        {"role": "assistant", "content": periodos.PEDIDO_PERIODO},
        {"role": "user", "content": periodo},
    ]
    assert assistente_admin.contextualizar_periodo(periodo, historico) == f"{pergunta} {periodo}"


def test_admin_exige_consulta_antes_de_afirmar_dados(monkeypatch):
    pergunta = "qual a receita da rede neste ano?"
    monkeypatch.setattr(repositorio, "id_usuario_ativo", lambda *_args: uuid4())
    monkeypatch.setattr(
        repositorio, "gravar_pergunta", lambda *_args: [{"role": "user", "content": pergunta}]
    )
    monkeypatch.setattr(repositorio, "gravar_resposta", lambda *_args: None)
    monkeypatch.setattr(repositorio, "marcar_pergunta_sem_resposta", lambda *_args: None)
    monkeypatch.setattr(provedor, "completar", lambda *_args: {
        "texto": "Receita inventada de R$ 999", "chamadas": [],
        "tokens_entrada": 1, "tokens_saida": 1,
    })
    resposta = assistente_admin.enviar_mensagem(
        lambda operacao: operacao(None), admin(),
        Settings(_env_file=None, database_url="postgresql://localhost/teste", groq_api_key="teste"),
        uuid4(), pergunta,
    )
    assert "não posso confirmar" in resposta["resposta"].lower()
    assert "999" not in resposta["resposta"]


def test_gerente_nao_pode_usar_servico_do_admin(monkeypatch):
    gerente = UsuarioAtual(id_auth=uuid4(), papel=Papel.GERENTE_LOJA, id_loja=uuid4())
    monkeypatch.setattr(
        repositorio, "id_usuario_ativo",
        lambda *_args: (_ for _ in ()).throw(AssertionError("não deveria consultar o banco")),
    )
    with pytest.raises(service.AcessoNegado):
        assistente_admin.enviar_mensagem(
            lambda operacao: operacao(None), gerente,
            Settings(_env_file=None, database_url="postgresql://localhost/teste"),
            uuid4(), "qual a receita da rede este ano?",
        )


@pytest.mark.parametrize(
    "pergunta",
    ["Qual o CPF de Maria?", "Qual o telefone de João?", "Quem é o gerente?"],
)
def test_admin_exige_ferramenta_para_dados_pessoais_e_equipe(pergunta):
    assert assistente_admin.exige_ferramenta(pergunta)


@pytest.mark.parametrize(
    "mensagens",
    [
        ["qual a receita da rede?", "dos ultimos 30 dias"],
        ["quanto ganhamos de dinheiro esse ano?", "faturamento", "este ano"],
    ],
)
def test_admin_conversa_completa_retoma_periodo_e_consulta_rede(monkeypatch, mensagens):
    usuario = admin()
    conversa = uuid4()
    historico = []
    consultas = []

    def gravar_pergunta(_c, id_conversa, _id_usuario, texto, _tipo):
        assert id_conversa == conversa
        historico.append({"role": "user", "content": texto})
        return historico.copy()

    def gravar_resposta(_c, id_conversa, texto, *_args):
        assert id_conversa == conversa
        historico.append({"role": "assistant", "content": texto})

    monkeypatch.setattr(repositorio, "id_usuario_ativo", lambda *_args: uuid4())
    monkeypatch.setattr(repositorio, "gravar_pergunta", gravar_pergunta)
    monkeypatch.setattr(repositorio, "gravar_resposta", gravar_resposta)
    monkeypatch.setattr(repositorio, "gravar_ferramenta", lambda *_args: None)

    def dashboard(_c, _usuario, *, inicio, fim, filtro):
        consultas.append((inicio, fim, filtro.id_loja))
        return {"atual": {"faturamento": 123}}

    monkeypatch.setattr(ferramentas.gerencia_service, "montar_dashboard", dashboard)
    turnos = iter([
        {"texto": "", "tokens_entrada": 1, "tokens_saida": 1, "chamadas": [{
            "id": "1", "name": "consultar_vendas",
            "arguments": {"inicio": "2026-01-01", "fim": "2026-01-31"},
        }]},
        {"texto": "Faturamento: R$ 123", "tokens_entrada": 1, "tokens_saida": 1, "chamadas": []},
    ])
    monkeypatch.setattr(provedor, "completar", lambda *_args: next(turnos))
    config = Settings(
        _env_file=None, database_url="postgresql://localhost/teste",
        groq_api_key="teste", gemini_api_key="teste",
    )
    respostas = [
        assistente_admin.enviar_mensagem(
            lambda operacao: operacao(None), usuario, config, conversa, texto
        )
        for texto in mensagens
    ]
    assert "Qual período" in respostas[-2]["resposta"]
    assert respostas[-1]["resposta"] == "Faturamento: R$ 123"
    assert len(consultas) == 1
    assert consultas[0][2] is None


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
