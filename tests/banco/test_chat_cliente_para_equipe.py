"""O que o cliente escreve chega ao atendimento (e a resposta volta), contra um Postgres real."""

from uuid import uuid4

import pytest

from app.chat import service as chat
from app.cliente import repositorio as cliente_repo
from app.cliente.erros import ChamadoClienteNaoEncontrado
from tests.banco.test_chat_repositorio import SemCommit, como_token, contexto

pytestmark = pytest.mark.banco


@pytest.fixture
def sa_conn(sa_conn):
    return SemCommit(sa_conn)


def test_mensagem_do_cliente_chega_a_equipe_e_a_resposta_volta(sa_conn, fab_sa):
    fab = fab_sa
    loja, outra_loja = fab.loja(), fab.loja()
    helena, bruno = fab.usuario("cliente"), fab.usuario("cliente")
    atendente = fab.usuario("atendente", loja=loja)
    gerente = fab.usuario("gerente_loja", loja=loja)
    de_fora = fab.usuario("atendente", loja=outra_loja)
    chamado = fab.atendimento(cliente=helena, loja=loja, assunto="Ajuste da manga")

    # O cliente escreve pelo portal (rota do cliente).
    nova = cliente_repo.enviar_mensagem_chamado_cliente(
        sa_conn, helena.id, chamado, "Preciso ajustar a manga"
    )
    assert nova["texto"] == "Preciso ajustar a manga"

    # Atendente e gerente da loja veem na caixa: aguardando resposta e uma nao lida.
    for quem in (atendente, gerente):
        _, escopo = contexto(sa_conn, quem)
        caixa = chat.listar(
            sa_conn, escopo, secao="todas", apenas_nao_lidas=False, limit=50, offset=0
        )
        item = next(i for i in caixa["itens"] if i["id_atendimento"] == chamado)
        assert item["ultima_mensagem"]["texto"] == "Preciso ajustar a manga"
        assert item["ultima_mensagem"]["autor"] == "cliente"
        assert item["aguardando_resposta"] is True
        assert item["nao_lidas"] == 1
        dentro = chat.mensagens(sa_conn, escopo, chamado, apos=None, limit=50)["mensagens"]
        assert [m["texto"] for m in dentro] == ["Preciso ajustar a manga"]

    # Equipe de outra loja nao enxerga a conversa.
    _, escopo_fora = contexto(sa_conn, de_fora)
    caixa_fora = chat.listar(
        sa_conn, escopo_fora, secao="todas", apenas_nao_lidas=False, limit=50, offset=0
    )
    assert chamado not in [i["id_atendimento"] for i in caixa_fora["itens"]]

    # O atendente responde pelo chat; o cliente ve a resposta na conversa dele.
    token, escopo = contexto(sa_conn, atendente)
    chat.enviar_mensagem(sa_conn, token, escopo, chamado, "Pode trazer na loja amanha")
    conversa = cliente_repo.listar_mensagens_chamado_cliente(sa_conn, helena.id, chamado)
    assert [(m["autor"], m["texto"]) for m in conversa] == [
        ("cliente", "Preciso ajustar a manga"),
        ("atendente", "Pode trazer na loja amanha"),
    ]

    # Chamado novo aberto pelo portal: a descricao vira a primeira mensagem na caixa da loja.
    aberto = cliente_repo.criar_chamado_cliente(
        sa_conn,
        helena.id,
        {
            "assunto": "Troca de tamanho",
            "categoria": "troca_devolucao",
            "descricao": "Quero trocar o M pelo G",
            "id_loja": loja,
        },
    )
    _, escopo = contexto(sa_conn, gerente)
    caixa = chat.listar(sa_conn, escopo, secao="todas", apenas_nao_lidas=False, limit=50, offset=0)
    novo = next(
        i for i in caixa["itens"] if str(i["id_atendimento"]) == str(aberto["id_atendimento"])
    )
    assert novo["ultima_mensagem"]["texto"] == "Quero trocar o M pelo G"
    assert novo["ultima_mensagem"]["autor"] == "cliente"

    # Outro cliente nao escreve nem le a conversa da Helena.
    with pytest.raises(ChamadoClienteNaoEncontrado):
        cliente_repo.enviar_mensagem_chamado_cliente(sa_conn, bruno.id, chamado, "intruso")
    with pytest.raises(ChamadoClienteNaoEncontrado):
        cliente_repo.listar_mensagens_chamado_cliente(sa_conn, bruno.id, uuid4())
    assert como_token(atendente).id_loja == loja
