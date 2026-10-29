"""Montagem dos e-mails do operador de estoque, sem banco."""

from datetime import UTC, date, datetime

from app.automacoes import emails_estoque

HOJE = date(2026, 10, 30)
PAINEL = "https://exemplo.test/painel/estoque"


def _loja(**listas):
    base = {
        "loja": "Barra <b>",
        "abaixo_do_minimo": [],
        "para_responder": [],
        "pedidos_sem_resposta": [],
        "a_receber": [],
        "ajustes_pendentes": [],
    }
    return {**base, **listas}


def _peca(n, saldo=0):
    return {
        "sku": f"S-{n}",
        "produto": f"Camisa <{n}>",
        "cor": "azul",
        "tamanho": "M",
        "saldo": saldo,
        "minimo": 1,
        "lojas_com_sobra": [],
    }


def test_texto_do_banco_e_escapado():
    email = emails_estoque.diario(_loja(abaixo_do_minimo=[_peca(1)]), {}, HOJE, PAINEL, 30)

    assert "Camisa &lt;1&gt;" in email["html"] and "<1>" not in email["html"]
    assert "Barra &lt;b&gt;" in email["html"]
    assert email["assunto"] == "Estoque do dia · Barra <b>: 1 item para resolver"


def test_lista_longa_mostra_o_limite_e_manda_o_resto_para_o_painel():
    pecas = [_peca(n) for n in range(45)]
    email = emails_estoque.diario(_loja(abaixo_do_minimo=pecas), {}, HOJE, PAINEL, 30)

    assert email["html"].count("S-") == 30
    assert "Abaixo do mínimo (45)" in email["html"]
    assert "E mais 15 no painel" in email["html"]
    assert email["assunto"].endswith("45 itens para resolver")


def test_reposicao_a_rede_sem_origem():
    pedido = {
        **_peca(1),
        "quantidade": 2,
        "origem": None,
        "destino": "Barra",
        "solicitada_em": datetime(2026, 10, 27, 15, tzinfo=UTC),
    }
    email = emails_estoque.diario(_loja(pedidos_sem_resposta=[pedido]), {}, HOJE, PAINEL, 30)

    assert "rede (qualquer loja)" in email["html"] and "27/10/2026" in email["html"]


def test_semanal_em_reais_e_peca_que_nunca_vendeu():
    loja = {
        "loja": "Savassi",
        "total_itens": 1,
        "total_unidades": 3,
        "total_valor": 12345.6,
        "itens": [{**_peca(1, 3), "valor_parado": 12345.6, "ultima_venda": None}],
    }
    email = emails_estoque.semanal(loja, 60, "criterio", HOJE, PAINEL)

    assert "R$ 12.345,60" in email["html"] and "nunca" in email["html"]
    assert email["assunto"] == "Estoque parado · Savassi: 1 peça sem venda há 60+ dias"
