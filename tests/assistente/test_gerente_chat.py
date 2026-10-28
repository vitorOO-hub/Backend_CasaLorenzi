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


def test_ferramenta_usa_loja_do_token_e_nao_recebe_loja_do_modelo(monkeypatch):
    usuario = gerente_usuario()
    chamada = {}

    def montar_reposicao(_conexao, filtro, *, limite):
        chamada.update(id_loja=filtro.id_loja, limite=limite)
        return {"total": 0, "itens": []}

    monkeypatch.setattr(gerente.gerencia_service, "montar_reposicao", montar_reposicao)

    resultado = gerente.executar_ferramenta(
        None, usuario, "consultar_reposicao_unidade", {}
    )

    assert chamada == {"id_loja": usuario.id_loja, "limite": 20}
    assert resultado == {"total": 0, "itens": []}
    with pytest.raises(FerramentaInvalida, match="Argumentos inválidos"):
        gerente.executar_ferramenta(
            None,
            usuario,
            "consultar_reposicao_unidade",
            {"id_loja": str(uuid4())},
        )


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


def test_gerente_sem_loja_nao_acessa_chat():
    usuario = UsuarioAtual(id_auth=uuid4(), papel=Papel.GERENTE_LOJA)

    with pytest.raises(service.AcessoNegado):
        gerente.criar_conversa(None, usuario, None)
