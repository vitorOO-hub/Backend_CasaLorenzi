"""Testes das rotas de atendimento sem banco real."""

from app.atendimento.erros import AtendimentoNaoEncontrado
from app.core.db import get_executar

ID_UUID = "6f1c3a52-6a4e-4c8e-9a39-0f1f2b6f2f10"
LINHA = {"id_atendimento": ID_UUID, "status": "Aberto"}

ROTAS_ATENDIMENTO_ESPERADAS = {
    ("GET", "/atendimentos/opcoes/{nome_opcao}"),
    ("GET", "/atendimentos"),
    ("POST", "/atendimentos"),
    ("GET", "/atendimentos/{id_atendimento}"),
    ("PATCH", "/atendimentos/{id_atendimento}"),
    ("PATCH", "/atendimentos/{id_atendimento}/status"),
    ("PATCH", "/atendimentos/{id_atendimento}/responsavel"),
    ("GET", "/atendimentos/{id_atendimento}/mensagens"),
    ("POST", "/atendimentos/{id_atendimento}/mensagens"),
    ("GET", "/atendimentos/{id_atendimento}/itens"),
    ("POST", "/atendimentos/{id_atendimento}/itens"),
    ("POST", "/atendimentos/{id_atendimento}/avaliacao"),
}


def usar_executor(app, executor):
    app.dependency_overrides[get_executar] = lambda: executor


def devolve(resultado):
    return lambda _operacao: resultado


def levanta(erro):
    def executor(_operacao):
        raise erro

    return executor


def test_rotas_de_atendimento_estao_registradas(cliente):
    caminhos = cliente.get("/openapi.json").json()["paths"]
    registradas = {
        (metodo.upper(), caminho) for caminho, itens in caminhos.items() for metodo in itens
    }
    assert ROTAS_ATENDIMENTO_ESPERADAS.issubset(registradas)


def test_criar_atendimento_responde_201(app, cliente):
    usar_executor(app, devolve(LINHA))
    resposta = cliente.post(
        "/atendimentos",
        json={
            "id_cliente": ID_UUID,
            "id_canal_atendimento": ID_UUID,
            "id_categoria_atendimento": ID_UUID,
            "id_prioridade_atendimento": ID_UUID,
            "id_status_atendimento": ID_UUID,
        },
    )
    assert resposta.status_code == 201
    assert resposta.json() == LINHA


def test_atendimento_inexistente_responde_404(app, cliente):
    usar_executor(app, levanta(AtendimentoNaoEncontrado()))
    resposta = cliente.get(f"/atendimentos/{ID_UUID}")
    assert resposta.status_code == 404
    assert resposta.json() == {"detail": "Atendimento nao encontrado"}


def test_atualizar_status_responde_200(app, cliente):
    usar_executor(app, devolve({"id_atendimento": ID_UUID, "id_status_atendimento": ID_UUID}))
    resposta = cliente.patch(
        f"/atendimentos/{ID_UUID}/status",
        json={"id_status_atendimento": ID_UUID},
    )
    assert resposta.status_code == 200
    assert resposta.json()["id_atendimento"] == ID_UUID


def test_criar_mensagem_responde_201(app, cliente):
    usar_executor(app, devolve({"id_mensagem": ID_UUID, "texto": "Ola"}))
    resposta = cliente.post(
        f"/atendimentos/{ID_UUID}/mensagens",
        json={"id_usuario_remetente": ID_UUID, "texto": "Ola"},
    )
    assert resposta.status_code == 201
    assert resposta.json()["id_mensagem"] == ID_UUID


def test_mensagem_vazia_e_rejeitada(cliente):
    resposta = cliente.post(
        f"/atendimentos/{ID_UUID}/mensagens",
        json={"id_usuario_remetente": ID_UUID, "texto": ""},
    )
    assert resposta.status_code == 422


def test_referencia_invalida_responde_409(app, cliente, erro_integridade):
    usar_executor(app, levanta(erro_integridade("23503")))
    resposta = cliente.post(
        "/atendimentos",
        json={
            "id_cliente": ID_UUID,
            "id_canal_atendimento": ID_UUID,
            "id_categoria_atendimento": ID_UUID,
            "id_prioridade_atendimento": ID_UUID,
            "id_status_atendimento": ID_UUID,
        },
    )
    assert resposta.status_code == 409
    assert resposta.json() == {
        "detail": "Alguma referencia do atendimento nao existe ou nao pode ser usada"
    }


def test_avaliacao_rejeita_nota_fora_do_intervalo(cliente):
    resposta = cliente.post(
        f"/atendimentos/{ID_UUID}/avaliacao",
        json={"nota": 6, "comentario": "Muito bom"},
    )
    assert resposta.status_code == 422
