"""O que o cliente escreve chega ao atendimento (e a resposta volta), contra um Postgres real."""

from uuid import uuid4

import pytest

from app.chamados import service as chamados
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
    # Sem ordem: no teste as duas mensagens nascem na mesma transacao (mesmo `now()`).
    assert {(m["autor"], m["texto"]) for m in conversa} == {
        ("cliente", "Preciso ajustar a manga"),
        ("atendente", "Pode trazer na loja amanha"),
    }

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


def test_chamado_aberto_no_portal_aparece_na_fila_de_chamados(sa_conn, fab_sa):
    fab = fab_sa
    loja, outra_loja = fab.loja(), fab.loja()
    cliente = fab.usuario("cliente")
    atendente = fab.usuario("atendente", loja=loja)
    gerente = fab.usuario("gerente_loja", loja=loja)
    fora = fab.usuario("atendente", loja=outra_loja)

    aberto = cliente_repo.criar_chamado_cliente(
        sa_conn,
        cliente.id,
        {
            "assunto": "Dúvida sobre tecido",
            "categoria": "outro",
            "descricao": "Quero entender melhor o tecido antes da compra.",
            "id_loja": str(loja),
        },
    )

    for quem in (atendente, gerente):
        token = como_token(quem)
        escopo = chamados.montar_escopo(sa_conn, token, None)
        fila = chamados.listar(
            sa_conn,
            escopo,
            situacao="abertos",
            responsavel="todos",
            prioridade=None,
            canal=None,
            categoria=None,
            limit=20,
            offset=0,
        )
        ids = {str(item["id_atendimento"]) for item in fila["itens"]}
        assert str(aberto["id_atendimento"]) in ids

    escopo_fora = chamados.montar_escopo(sa_conn, como_token(fora), None)
    fila_fora = chamados.listar(
        sa_conn,
        escopo_fora,
        situacao="abertos",
        responsavel="todos",
        prioridade=None,
        canal=None,
        categoria=None,
        limit=20,
        offset=0,
    )
    assert str(aberto["id_atendimento"]) not in {
        str(item["id_atendimento"]) for item in fila_fora["itens"]
    }


def test_chamado_sem_loja_no_payload_cai_na_fila_geral_da_equipe(sa_conn, fab_sa):
    fab = fab_sa
    loja, outra_loja = fab.loja(), fab.loja()
    cliente = fab.usuario("cliente")
    atendente = fab.usuario("atendente", loja=loja)
    gerente = fab.usuario("gerente_loja", loja=loja)
    atendente_outra_loja = fab.usuario("atendente", loja=outra_loja)
    gerente_outra_loja = fab.usuario("gerente_loja", loja=outra_loja)

    aberto = cliente_repo.criar_chamado_cliente(
        sa_conn,
        cliente.id,
        {
            "assunto": "Ajuste sem loja selecionada",
            "categoria": "outro",
            "descricao": "Abri pelo portal sem escolher uma loja.",
        },
    )

    assert aberto["id_loja"] is None
    for quem in (atendente, gerente, atendente_outra_loja, gerente_outra_loja):
        token = como_token(quem)
        escopo = chamados.montar_escopo(sa_conn, token, None)
        fila = chamados.listar(
            sa_conn,
            escopo,
            situacao="abertos",
            responsavel="todos",
            prioridade=None,
            canal=None,
            categoria=None,
            limit=20,
            offset=0,
        )
        assert str(aberto["id_atendimento"]) in {
            str(item["id_atendimento"]) for item in fila["itens"]
        }


def _ids_na_fila(sa_conn, usuario) -> set[str]:
    escopo = chamados.montar_escopo(sa_conn, como_token(usuario), None)
    fila = chamados.listar(
        sa_conn,
        escopo,
        situacao="abertos",
        responsavel="todos",
        prioridade=None,
        canal=None,
        categoria=None,
        limit=20,
        offset=0,
    )
    return {str(item["id_atendimento"]) for item in fila["itens"]}


def test_chamado_com_pedido_sem_loja_escolhida_vai_para_a_fila_geral(sa_conn, fab_sa):
    # O pedido e contexto, nao decide a loja: sem escolha do cliente, qualquer atendente ve.
    fab = fab_sa
    loja, outra_loja = fab.loja(), fab.loja()
    cliente = fab.usuario("cliente")
    pedido = fab.pedido(loja=loja, cliente=cliente)
    da_loja = fab.usuario("atendente", loja=loja)
    de_outra = fab.usuario("atendente", loja=outra_loja)

    aberto = cliente_repo.criar_chamado_cliente(
        sa_conn,
        cliente.id,
        {
            "assunto": "Chamado sobre pedido",
            "categoria": "outro",
            "descricao": "Preciso falar sobre um pedido especifico.",
            "id_pedido": str(pedido),
        },
    )

    assert aberto["id_loja"] is None
    assert str(aberto["id_pedido"]) == str(pedido)
    assert str(aberto["id_atendimento"]) in _ids_na_fila(sa_conn, da_loja)
    assert str(aberto["id_atendimento"]) in _ids_na_fila(sa_conn, de_outra)


def test_chamado_com_pedido_e_loja_escolhida_vai_so_para_essa_loja(sa_conn, fab_sa):
    fab = fab_sa
    loja_do_pedido, escolhida = fab.loja(), fab.loja()
    cliente = fab.usuario("cliente")
    pedido = fab.pedido(loja=loja_do_pedido, cliente=cliente)
    da_escolhida = fab.usuario("atendente", loja=escolhida)
    da_loja_do_pedido = fab.usuario("atendente", loja=loja_do_pedido)

    aberto = cliente_repo.criar_chamado_cliente(
        sa_conn,
        cliente.id,
        {
            "assunto": "Chamado sobre pedido",
            "categoria": "outro",
            "descricao": "Quero resolver na loja que escolhi.",
            "id_pedido": str(pedido),
            "id_loja": str(escolhida),
        },
    )

    assert aberto["id_loja"] == escolhida
    assert str(aberto["id_atendimento"]) in _ids_na_fila(sa_conn, da_escolhida)
    assert str(aberto["id_atendimento"]) not in _ids_na_fila(sa_conn, da_loja_do_pedido)
