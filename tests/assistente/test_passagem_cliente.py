"""O que o atendente recebe quando a conversa sai do assistente."""

from app.assistente.cliente.passagem import LIMITE_DESCRICAO, montar_descricao


def test_descricao_tem_motivo_resumo_e_conversa_em_ordem():
    mensagens = [
        {"autor": "usuario", "texto": "Meu pedido PD-12 nao chegou."},
        {"autor": "assistente", "texto": "Vou verificar."},
    ]
    descricao = montar_descricao(
        mensagens, motivo="Entrega atrasada", resumo="Pedido PD-12 atrasado."
    )
    assert descricao.splitlines() == [
        "Chamado aberto pelo assistente do site.",
        "Motivo: Entrega atrasada",
        "Loja: nao identificada (fila geral)",
        "Resumo do assistente: Pedido PD-12 atrasado.",
        "",
        "Conversa com o assistente:",
        "Cliente: Meu pedido PD-12 nao chegou.",
        "Assistente: Vou verificar.",
    ]


def test_conversa_longa_mantem_as_mensagens_mais_recentes_dentro_do_limite():
    mensagens = [{"autor": "usuario", "texto": f"mensagem {i} " + "x" * 300} for i in range(40)]
    descricao = montar_descricao(mensagens, motivo="m", resumo=None)
    assert len(descricao) <= LIMITE_DESCRICAO
    assert "[mensagens anteriores omitidas]" in descricao
    assert "mensagem 39 " in descricao and "mensagem 0 " not in descricao
    assert "Resumo do assistente" not in descricao
