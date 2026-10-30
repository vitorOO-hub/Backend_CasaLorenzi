from uuid import uuid4

import pytest

from app.assistente import gerente, provedor, repositorio, service
from app.assistente.ferramentas import FerramentaInvalida
from app.core.config import Settings
from app.core.papeis import Papel, UsuarioAtual


def gerente_usuario(loja=None):
    return UsuarioAtual(
        id_auth=uuid4(),
        papel=Papel.GERENTE_LOJA,
        id_loja=loja or uuid4(),
    )


@pytest.mark.parametrize(
    "pergunta",
    [
        "Compare o faturamento da unidade em janeiro e fevereiro",
        "Quais peças precisam de reposição?",
        "O que está parado no estoque há 60 dias?",
        "Quantas pendências de ajustes e transferências temos?",
        "Mostre o resumo da minha loja",
        "Quais peças foram mais vendidas nesta semana?",
        "Como foi o desempenho das marcas neste mês?",
        "Qual foi o movimento por dia na semana passada?",
        "Qual o saldo em estoque da camiseta?",
        "Quais peças estão esgotadas?",
        "Quantos ajustes estão pendentes para aprovar?",
        "Mostre as movimentações de estoque",
        "Quanto vendemos neste mês?",
        "Quanto a loja faturou neste ano?",
        "Quanto vendeu a loja na semana passada?",
    ],
)
def test_pergunta_de_funcionalidade_do_gerente_e_permitida(pergunta):
    assert gerente.pergunta_no_escopo(pergunta)


@pytest.mark.parametrize(
    "pergunta",
    [
        "Liste o CPF de todos os clientes",
        "Compare as vendas de todas as lojas da rede",
        "Aprove este ajuste de estoque",
        "Quantos funcionários estão na equipe?",
        "Qual é a previsão do tempo?",
    ],
)
def test_pergunta_fora_das_funcionalidades_do_gerente_e_barrada(pergunta):
    assert not gerente.pergunta_no_escopo(pergunta)


def test_ferramentas_do_gerente_nao_expoem_ferramentas_admin():
    nomes = {ferramenta["name"] for ferramenta in gerente.FERRAMENTAS}

    assert nomes == {
        "consultar_movimentacoes_unidade",
        "consultar_saldo_unidade",
        "consultar_vendas_unidade",
        "consultar_reposicao_unidade",
        "consultar_estoque_parado_unidade",
        "consultar_pendencias_unidade",
        "consultar_resumo_unidade",
    }
    assert all(
        "id_loja" not in ferramenta["parameters"]["properties"]
        for ferramenta in gerente.FERRAMENTAS
    )


def test_saldo_usa_loja_autenticada_e_rejeita_outra_loja(monkeypatch):
    usuario = gerente_usuario()
    capturado = {}

    def montar_saldo(_conexao, filtro, *, limit, offset):
        capturado.update(filtro=filtro, limit=limit, offset=offset)
        return {"total": 0, "itens": [], "resumo": {"unidades": 500}}

    monkeypatch.setattr(gerente.estoque_service, "montar_saldo", montar_saldo)
    resultado = gerente.executar_ferramenta(
        None, usuario, "consultar_saldo_unidade", {"busca": "camisa"}
    )
    assert "resumo" not in resultado
    assert capturado["filtro"].id_loja == usuario.id_loja
    assert capturado["filtro"].busca == "camisa"
    with pytest.raises(FerramentaInvalida):
        gerente.executar_ferramenta(
            None, usuario, "consultar_saldo_unidade", {"id_loja": str(uuid4())}
        )


def test_movimentacoes_usam_loja_do_token(monkeypatch):
    usuario = gerente_usuario()
    recebido = {}

    def filtro(_conexao, _usuario, **kwargs):
        recebido.update(kwargs)
        return "filtro"

    monkeypatch.setattr(gerente.estoque_service, "filtro_de_movimentacoes", filtro)
    monkeypatch.setattr(
        gerente.estoque_service, "montar_movimentacoes",
        lambda _c, _f, **_k: {"total": 0, "itens": []},
    )
    gerente.executar_ferramenta(
        None, usuario, "consultar_movimentacoes_unidade", {"tipo": "entrada"}
    )
    assert recebido["id_loja"] == usuario.id_loja
    assert recebido["grupo"] == "entrada"
    with pytest.raises(FerramentaInvalida):
        gerente.executar_ferramenta(
            None, usuario, "consultar_movimentacoes_unidade", {"id_loja": str(uuid4())}
        )


def test_ferramenta_usa_loja_do_token_e_nao_recebe_loja_do_modelo(monkeypatch):
    usuario = gerente_usuario()
    chamada = {}

    def montar_reposicao(_conexao, filtro, *, limite, ids_produto=None):
        chamada.update(id_loja=filtro.id_loja, limite=limite, ids_produto=ids_produto)
        return {"total": 0, "itens": []}

    monkeypatch.setattr(gerente.gerencia_service, "montar_reposicao", montar_reposicao)

    resultado = gerente.executar_ferramenta(
        None, usuario, "consultar_reposicao_unidade", {}
    )

    assert chamada == {"id_loja": usuario.id_loja, "limite": 20, "ids_produto": None}
    assert resultado == {"total": 0, "itens": []}
    with pytest.raises(FerramentaInvalida, match="Argumentos inválidos"):
        gerente.executar_ferramenta(
            None,
            usuario,
            "consultar_reposicao_unidade",
            {"id_loja": str(uuid4())},
        )


def test_busca_literal_de_produto_nao_chama_gemini(monkeypatch):
    usuario = gerente_usuario()
    id_produto = uuid4()
    recebidos = {}
    monkeypatch.setattr(
        gerente.gerencia_repositorio,
        "produtos_da_unidade_por_texto",
        lambda _conn, id_loja, busca, **_kwargs: (
            recebidos.update(id_loja=id_loja, busca=busca) or [id_produto]
        ),
    )
    monkeypatch.setattr(
        gerente.embeddings,
        "gerar",
        lambda *_args: (_ for _ in ()).throw(AssertionError("não deveria gerar embedding")),
    )
    monkeypatch.setattr(
        gerente.gerencia_service,
        "montar_reposicao",
        lambda _conn, filtro, *, limite, ids_produto: {
            **recebidos,
            "id_loja_filtro": filtro.id_loja,
            "ids_produto": ids_produto,
            "limite": limite,
        },
    )

    resultado = gerente.executar_ferramenta(
        None,
        usuario,
        "consultar_reposicao_unidade",
        {"busca_produto": "Camisa de linho"},
    )

    assert resultado == {
        "id_loja": usuario.id_loja,
        "busca": "Camisa de linho",
        "id_loja_filtro": usuario.id_loja,
        "ids_produto": (id_produto,),
        "limite": 20,
    }


def test_fallback_semantico_filtra_candidatos_pela_loja_do_token(monkeypatch):
    usuario = gerente_usuario()
    id_produto = uuid4()
    chamadas = {}
    monkeypatch.setattr(
        gerente.gerencia_repositorio, "produtos_da_unidade_por_texto", lambda *_a, **_k: []
    )
    monkeypatch.setattr(
        gerente.embeddings,
        "gerar",
        lambda texto, _chave: (chamadas.update(texto=texto) or [0.1]),
    )
    monkeypatch.setattr(gerente.embeddings, "serializar", lambda _vetor: "[vetor]")

    def buscar_semanticos(_conn, id_loja, vetor, *, categoria, limite=20):
        chamadas.update(id_loja=id_loja, vetor=vetor, categoria=categoria, limite=limite)
        return [id_produto]

    monkeypatch.setattr(
        gerente.gerencia_repositorio,
        "produtos_semanticos_da_unidade",
        buscar_semanticos,
    )
    monkeypatch.setattr(
        gerente.gerencia_service,
        "montar_reposicao",
        lambda _conn, filtro, *, limite, ids_produto: {
            "id_loja": filtro.id_loja,
            "ids_produto": ids_produto,
            "limite": limite,
        },
    )
    configuracoes = Settings(
        _env_file=None,
        database_url="postgresql://localhost/teste",
        gemini_api_key="chave-gemini-falsa",
    )

    resultado = gerente.executar_ferramenta(
        None,
        usuario,
        "consultar_reposicao_unidade",
        {"categoria": "Camisas", "busca_produto": "fibras vegetais"},
        configuracoes,
    )

    assert chamadas == {
        "texto": "fibras vegetais",
        "id_loja": usuario.id_loja,
        "vetor": "[vetor]",
        "categoria": "camisas",
        "limite": 20,
    }
    assert resultado == {
        "id_loja": usuario.id_loja,
        "ids_produto": (id_produto,),
        "limite": 20,
    }


def test_busca_semantica_sem_candidatos_nao_consulta_reposicao_ampla(monkeypatch):
    usuario = gerente_usuario()
    monkeypatch.setattr(
        gerente.gerencia_repositorio, "produtos_da_unidade_por_texto", lambda *_a, **_k: []
    )
    monkeypatch.setattr(gerente.embeddings, "gerar", lambda *_a: [0.1])
    monkeypatch.setattr(gerente.embeddings, "serializar", lambda _vetor: "[vetor]")
    monkeypatch.setattr(
        gerente.gerencia_repositorio,
        "produtos_semanticos_da_unidade",
        lambda *_a, **_k: [],
    )
    monkeypatch.setattr(
        gerente.gerencia_service,
        "montar_reposicao",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("busca vazia não pode consultar reposição sem filtro")
        ),
    )
    configuracoes = Settings(
        _env_file=None,
        database_url="postgresql://localhost/teste",
        gemini_api_key="chave-gemini-falsa",
    )

    resultado = gerente.executar_ferramenta(
        None,
        usuario,
        "consultar_reposicao_unidade",
        {"busca_produto": "item que não existe"},
        configuracoes,
    )

    assert resultado == {"total": 0, "itens": []}


def test_ferramenta_rejeita_usuario_que_nao_e_gerente():
    admin = UsuarioAtual(id_auth=uuid4(), papel=Papel.ADMIN)

    with pytest.raises(FerramentaInvalida, match="exclusiva do gerente"):
        gerente.executar_ferramenta(None, admin, "consultar_reposicao_unidade", {})


def test_pergunta_fora_do_escopo_nao_chama_provedor(monkeypatch):
    usuario = gerente_usuario()
    monkeypatch.setattr(repositorio, "id_usuario_ativo", lambda *_args: uuid4())
    monkeypatch.setattr(repositorio, "gravar_pergunta", lambda *_args: [])
    monkeypatch.setattr(repositorio, "gravar_resposta", lambda *_args: None)

    def provedor_nao_deve_ser_chamado(*_args):
        raise AssertionError("pergunta fora do escopo chegou ao provedor")

    monkeypatch.setattr(provedor, "completar", provedor_nao_deve_ser_chamado)

    def executar_db(operacao):
        return operacao(None)

    configuracoes = Settings(
        _env_file=None,
        database_url="postgresql://localhost/teste",
        groq_api_key="chave-groq-falsa",
        gemini_api_key="chave-gemini-falsa",
    )

    resposta = gerente.enviar_mensagem(
        executar_db, usuario, configuracoes, uuid4(), "Liste o CPF dos clientes"
    )

    assert "somente sobre" in resposta["resposta"]


def test_consulta_de_vendas_sem_periodo_pede_esclarecimento_sem_chamar_provedor(monkeypatch):
    usuario = gerente_usuario()
    monkeypatch.setattr(repositorio, "id_usuario_ativo", lambda *_args: uuid4())
    monkeypatch.setattr(repositorio, "gravar_pergunta", lambda *_args: [])
    monkeypatch.setattr(repositorio, "gravar_resposta", lambda *_args: None)
    monkeypatch.setattr(
        provedor,
        "completar",
        lambda *_args: (_ for _ in ()).throw(AssertionError("não deveria chamar o provedor")),
    )

    resposta = gerente.enviar_mensagem(
        lambda operacao: operacao(None),
        usuario,
        Settings(
            _env_file=None,
            database_url="postgresql://localhost/teste",
            groq_api_key="chave-groq-falsa",
            gemini_api_key="chave-gemini-falsa",
        ),
        uuid4(),
        "Qual foi o faturamento da minha unidade?",
    )

    assert "Qual período" in resposta["resposta"]


def test_pergunta_em_linguagem_natural_sobre_vendas_pede_periodo():
    pergunta = "Quanto a loja vendeu?"
    assert gerente.pergunta_no_escopo(pergunta)
    assert gerente.esclarecimento_necessario(pergunta) == gerente._PEDIDO_PERIODO


def test_pergunta_sobre_lucro_explica_limitacao_sem_inventar_valor(monkeypatch):
    usuario = gerente_usuario()
    monkeypatch.setattr(repositorio, "id_usuario_ativo", lambda *_args: uuid4())
    monkeypatch.setattr(repositorio, "gravar_pergunta", lambda *_args: [])
    monkeypatch.setattr(repositorio, "gravar_resposta", lambda *_args: None)
    monkeypatch.setattr(
        provedor, "completar",
        lambda *_args: (_ for _ in ()).throw(AssertionError("não deveria chamar o provedor")),
    )
    resposta = gerente.enviar_mensagem(
        lambda operacao: operacao(None), usuario,
        Settings(_env_file=None, database_url="postgresql://localhost/teste"),
        uuid4(), "qual o lucro desse ano?",
    )
    assert "não consigo consultar o lucro" in resposta["resposta"]
    assert "diferente de faturamento" in resposta["resposta"]


def test_ganhos_ambiguos_pedem_esclarecimento_sem_assumir_lucro(monkeypatch):
    usuario = gerente_usuario()
    monkeypatch.setattr(repositorio, "id_usuario_ativo", lambda *_args: uuid4())
    monkeypatch.setattr(repositorio, "gravar_pergunta", lambda *_args: [])
    monkeypatch.setattr(repositorio, "gravar_resposta", lambda *_args: None)
    monkeypatch.setattr(
        provedor, "completar",
        lambda *_args: (_ for _ in ()).throw(AssertionError("não deveria chamar o provedor")),
    )
    resposta = gerente.enviar_mensagem(
        lambda operacao: operacao(None), usuario,
        Settings(_env_file=None, database_url="postgresql://localhost/teste"),
        uuid4(), "quanto ganhamos de dinheiro esse ano?",
    )
    assert "faturamento ou o lucro" in resposta["resposta"]
    assert "lucro ainda não está disponível" in resposta["resposta"]


@pytest.mark.parametrize(
    ("assunto", "periodo"),
    [
        ("qual foi nossa receita?", "dos ultimos 30 dias"),
        ("faturamento", "este ano"),
        ("qual foi o faturamento?", "nos últimos 30 dias"),
        ("qual foi a receita?", "ano passado"),
        ("Quanto vendemos?", "no mês de outubro"),
        ("Quanto faturamos?", "nesses últimos 30 dias"),
        ("Quanto faturamos?", "deste ano"),
        ("Qual foi a receita?", "do ano de 2026"),
    ],
)
def test_resposta_de_periodo_continua_consulta_de_vendas(monkeypatch, assunto, periodo):
    usuario = gerente_usuario()
    historico = [
        {"role": "user", "content": assunto},
        {"role": "assistant", "content": gerente._PEDIDO_PERIODO},
        {"role": "user", "content": periodo},
    ]
    monkeypatch.setattr(repositorio, "id_usuario_ativo", lambda *_args: uuid4())
    monkeypatch.setattr(repositorio, "gravar_pergunta", lambda *_args: historico.copy())
    monkeypatch.setattr(repositorio, "gravar_resposta", lambda *_args: None)
    monkeypatch.setattr(repositorio, "gravar_ferramenta", lambda *_args: None)
    consultado = {}

    def dashboard(_conexao, _usuario, *, inicio, fim, filtro):
        consultado.update(inicio=inicio, fim=fim, loja=filtro.id_loja)
        return {"atual": {"faturamento": 123}}

    monkeypatch.setattr(gerente.gerencia_service, "montar_dashboard", dashboard)
    turnos = iter([
        {"texto": "", "tokens_entrada": 1, "tokens_saida": 1, "chamadas": [{
            "id": "1", "name": "consultar_vendas_unidade",
            "arguments": {"inicio": "2026-01-01", "fim": "2026-01-31"},
        }]},
        {"texto": "Faturamento: R$ 123", "tokens_entrada": 1, "tokens_saida": 1, "chamadas": []},
    ])
    mensagens_modelo = []

    def completar(_destino, _config, _instrucoes, mensagens, _ferramentas):
        mensagens_modelo.append(mensagens)
        return next(turnos)

    monkeypatch.setattr(provedor, "completar", completar)
    resposta = gerente.enviar_mensagem(
        lambda operacao: operacao(None), usuario,
        Settings(
            _env_file=None, database_url="postgresql://localhost/teste",
            groq_api_key="teste", gemini_api_key="teste",
        ),
        uuid4(), periodo,
    )
    assert resposta["resposta"] == "Faturamento: R$ 123"
    assert consultado["loja"] == usuario.id_loja
    assert mensagens_modelo[0][-1]["content"] == f"{assunto} {periodo}"


def test_periodo_nao_herda_assunto_sem_pedido_explicito_do_assistente():
    historico = [
        {"role": "user", "content": "qual foi nossa receita?"},
        {"role": "assistant", "content": "Outra resposta"},
        {"role": "user", "content": "este ano"},
    ]
    assert gerente.contextualizar_periodo("este ano", historico) == "este ano"


def test_periodo_recupera_assunto_apos_tentativa_anterior_recusada():
    historico = [
        {"role": "user", "content": "qual foi nossa receita?"},
        {"role": "assistant", "content": gerente._PEDIDO_PERIODO},
        {"role": "user", "content": "dos ultimos 30 dias"},
        {"role": "assistant", "content": (
            "Este assistente responde somente sobre vendas e indicadores da sua unidade, "
            "reposições, estoque parado e pendências do gerente. Para outros assuntos, "
            "procure a área responsável."
        )},
        {"role": "user", "content": "este ano"},
    ]
    assert gerente.contextualizar_periodo("este ano", historico) == (
        "qual foi nossa receita? este ano"
    )


@pytest.mark.parametrize("detalhe", ["resumo", "pecas_mais_vendidas", "marcas"])
def test_vendas_enviam_ao_modelo_apenas_detalhe_solicitado(monkeypatch, detalhe):
    usuario = gerente_usuario()
    dashboard = {
        "periodo": {"inicio": "2026-01-01", "fim": "2026-10-30"},
        "atual": {"faturamento": 123},
        "anterior": {"faturamento": 100},
        "escopo": {"id_loja": str(usuario.id_loja)},
        "serie_diaria": [{"data": str(i), "descricao": "x" * 100} for i in range(365)],
        "pecas_mais_vendidas": [{"nome": "Camisa", "unidades": 4}],
        "marcas": [{"marca": "A", "faturamento": 123}],
        "opcoes": {"marcas": ["x" * 100 for _ in range(100)]},
    }
    monkeypatch.setattr(gerente.gerencia_service, "montar_dashboard", lambda *_a, **_k: dashboard)
    resultado = gerente.executar_ferramenta(
        None, usuario, "consultar_vendas_unidade",
        {"inicio": "2026-01-01", "fim": "2026-10-30", "detalhe": detalhe},
    )
    assert resultado["atual"]["faturamento"] == 123
    assert "opcoes" not in resultado
    assert "serie_diaria" not in resultado
    if detalhe != "resumo":
        assert resultado[detalhe] == dashboard[detalhe]
    assert "aviso" not in service._json_para_modelo(resultado)[0]


def test_instrucoes_incluem_data_atual_no_fuso_de_sao_paulo(monkeypatch):
    from datetime import datetime

    class Relogio:
        @staticmethod
        def now(fuso):
            assert str(fuso) == "America/Sao_Paulo"
            return datetime(2026, 10, 30)

    capturado = {}
    monkeypatch.setattr(gerente, "datetime", Relogio)
    monkeypatch.setattr(
        gerente.service, "enviar_mensagem", lambda *_args, **kwargs: capturado.update(kwargs)
    )
    gerente.enviar_mensagem(None, gerente_usuario(), None, uuid4(), "faturamento deste ano")
    assert "Data atual em São Paulo: 2026-10-30" in capturado["instrucoes"]


@pytest.mark.parametrize(
    "mensagens",
    [
        ["qual foi nossa receita?", "dos ultimos 30 dias"],
        ["quanto ganhamos de dinheiro esse ano?", "faturamento", "este ano"],
    ],
)
def test_conversa_completa_lembra_assunto_apos_pedir_periodo(monkeypatch, mensagens):
    usuario = gerente_usuario()
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

    def dashboard(_c, _u, *, inicio, fim, filtro):
        consultas.append((inicio, fim, filtro.id_loja))
        return {"atual": {"faturamento": 123}}

    monkeypatch.setattr(gerente.gerencia_service, "montar_dashboard", dashboard)
    turnos = iter([
        {"texto": "", "tokens_entrada": 1, "tokens_saida": 1, "chamadas": [{
            "id": "1", "name": "consultar_vendas_unidade",
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
        gerente.enviar_mensagem(lambda operacao: operacao(None), usuario, config, conversa, texto)
        for texto in mensagens
    ]
    assert "Qual período" in respostas[-2]["resposta"]
    assert respostas[-1]["resposta"] == "Faturamento: R$ 123"
    assert len(consultas) == 1
    assert consultas[0][2] == usuario.id_loja


def test_periodo_nao_recupera_assunto_de_loja_fora_do_escopo():
    historico = [
        {"role": "user", "content": "faturamento de todas as lojas?"},
        {"role": "assistant", "content": gerente._PEDIDO_PERIODO},
        {"role": "user", "content": "este ano"},
    ]
    assert gerente.contextualizar_periodo("este ano", historico) == "este ano"


def test_termos_nao_listados_podem_ser_encaminhados_sem_perder_restricoes():
    assert gerente.pergunta_permitida("Como foi o resultado comercial do trimestre?")
    assert not gerente.pergunta_permitida("Mostre o resultado de todas as lojas")
    assert not gerente.pergunta_permitida("Mostre a senha de acesso")
    assert not gerente.pergunta_permitida("Aprove o ajuste de estoque")


def test_pergunta_nao_reconhecida_sem_ferramenta_nao_inventa_resposta(monkeypatch):
    usuario = gerente_usuario()
    pergunta = "Como está o resultado comercial do trimestre?"
    monkeypatch.setattr(repositorio, "id_usuario_ativo", lambda *_args: uuid4())
    monkeypatch.setattr(
        repositorio, "gravar_pergunta", lambda *_args: [{"role": "user", "content": pergunta}]
    )
    monkeypatch.setattr(repositorio, "gravar_resposta", lambda *_args: None)
    monkeypatch.setattr(repositorio, "marcar_pergunta_sem_resposta", lambda *_args: None)
    monkeypatch.setattr(provedor, "completar", lambda *_args: {
        "texto": "Resultado inventado: R$ 999", "tokens_entrada": 1,
        "tokens_saida": 1, "chamadas": [],
    })
    resposta = gerente.enviar_mensagem(
        lambda operacao: operacao(None), usuario,
        Settings(_env_file=None, database_url="postgresql://localhost/teste", groq_api_key="teste"),
        uuid4(), pergunta,
    )
    assert "não posso confirmar" in resposta["resposta"].lower()
    assert "999" not in resposta["resposta"]


def test_termos_nao_listados_podem_usar_ferramenta_permitida(monkeypatch):
    usuario = gerente_usuario()
    pergunta = "Como foi o resultado comercial do trimestre?"
    monkeypatch.setattr(repositorio, "id_usuario_ativo", lambda *_args: uuid4())
    monkeypatch.setattr(
        repositorio, "gravar_pergunta", lambda *_args: [{"role": "user", "content": pergunta}]
    )
    monkeypatch.setattr(repositorio, "gravar_resposta", lambda *_args: None)
    monkeypatch.setattr(repositorio, "gravar_ferramenta", lambda *_args: None)
    lojas = []

    def dashboard(_c, _u, *, filtro, **_kwargs):
        lojas.append(filtro.id_loja)
        return {"atual": {"faturamento": 123}}

    monkeypatch.setattr(gerente.gerencia_service, "montar_dashboard", dashboard)
    turnos = iter([
        {"texto": "", "tokens_entrada": 1, "tokens_saida": 1, "chamadas": [{
            "id": "1", "name": "consultar_vendas_unidade",
            "arguments": {"inicio": "2026-01-01", "fim": "2026-03-31"},
        }]},
        {"texto": "Faturamento: R$ 123", "tokens_entrada": 1, "tokens_saida": 1, "chamadas": []},
    ])
    monkeypatch.setattr(provedor, "completar", lambda *_args: next(turnos))
    resposta = gerente.enviar_mensagem(
        lambda operacao: operacao(None), usuario,
        Settings(_env_file=None, database_url="postgresql://localhost/teste", groq_api_key="teste"),
        uuid4(), pergunta,
    )
    assert resposta["resposta"] == "Faturamento: R$ 123"
    assert lojas == [usuario.id_loja]


def test_gerente_sem_loja_nao_acessa_chat():
    usuario = UsuarioAtual(id_auth=uuid4(), papel=Papel.GERENTE_LOJA)

    with pytest.raises(service.AcessoNegado):
        gerente.criar_conversa(None, usuario, None)
