"""Lorenzi+ contra um Postgres real: compra nova gera pontos pela regra da carga do Vulto+ e os
vencimentos lancados pelo banco batem com a regra em Python (app/cliente/vencimento_pontos.py)."""

import random
from collections import namedtuple
from datetime import timedelta

import pytest

from app.cliente.vencimento_pontos import CORTE_DA_CARGA, calcular

pytestmark = pytest.mark.banco

ANO = timedelta(days=365)
DIA = timedelta(days=1)


def status(c, codigo):
    return c.execute(
        "SELECT id_status_pedido FROM status_pedido WHERE codigo = %s", (codigo,)
    ).fetchone()[0]


def mudar(c, pedido, **campos):
    if "status" in campos:
        campos["id_status_pedido"] = status(c, campos.pop("status"))
    sets = ", ".join(f"{k} = %s" for k in campos)
    c.execute(f"UPDATE pedido SET {sets} WHERE id_pedido = %s", (*campos.values(), pedido))


def extrato(c, cliente):
    return c.execute(
        "SELECT tipo, pontos FROM movimento_pontos WHERE id_usuario = %s "
        "ORDER BY ocorrido_em, criado_em",
        (cliente.id,),
    ).fetchall()


@pytest.fixture
def cena(fab_sa):
    loja = fab_sa.loja()
    cliente = fab_sa.usuario("cliente")
    pedido = fab_sa.pedido(loja=loja, cliente=cliente)
    mudar(fab_sa.conn, pedido, canal_venda="loja")  # o padrao do banco e 'online'
    return fab_sa.conn, loja, cliente, pedido


@pytest.mark.parametrize(
    ("valor", "canal", "pontos"),
    [
        ("100.40", "loja", 100),
        ("100.50", "loja", 100),  # meio vai para o par, como o round do Python
        ("101.50", "loja", 102),
        ("100.60", "loja", 101),
        ("50.25", "online", 100),  # online em dobro, arredondado depois de multiplicar
        ("50.75", "online", 102),
        ("0", "loja", 0),
    ],
)
def test_pontos_da_compra(sa_conn, valor, canal, pontos):
    from sqlalchemy import text

    r = sa_conn.execute(
        text("SELECT public.pontos_da_compra(CAST(:v AS numeric), :c)"), {"v": valor, "c": canal}
    ).scalar()
    assert r == pontos


def test_compra_paga_na_loja_credita_com_validade_de_um_ano(cena):
    c, _, cliente, pedido = cena
    mudar(c, pedido, valor_total=259.9, status="pago")
    linha = c.execute(
        "SELECT tipo, pontos, id_pedido, vence_em - ocorrido_em FROM movimento_pontos "
        "WHERE id_usuario = %s",
        (cliente.id,),
    ).fetchall()
    assert linha == [("credito", 260, pedido, ANO)]


def test_criado_e_aguardando_nao_pontuam(cena):
    c, _, cliente, pedido = cena
    mudar(c, pedido, valor_total=300)
    mudar(c, pedido, status="aguardando_pagamento")
    assert extrato(c, cliente) == []


def test_checkout_grava_valor_depois_e_credita_uma_vez_em_dobro(cena):
    c, loja, cliente, _ = cena
    pedido = c.execute(
        "INSERT INTO pedido (numero_pedido, id_loja, id_cliente, id_status_pedido, valor_total) "
        "VALUES ('PD-SITE', %s, %s, %s, 0) RETURNING id_pedido",
        (loja, cliente.id, status(c, "pago")),
    ).fetchone()[0]
    mudar(c, pedido, valor_total=150, canal_venda="online")
    mudar(c, pedido, status="separado")
    mudar(c, pedido, status="entregue")
    assert extrato(c, cliente) == [("credito", 300)]


def test_cancelar_estorna_e_tira_da_categoria(cena, sa_conn):
    from app.cliente.repositorio import vulto_mais_cliente

    c, _, cliente, pedido = cena
    mudar(c, pedido, valor_total=2500, status="pago")
    mudar(c, pedido, status="cancelado")
    assert extrato(c, cliente) == [("credito", 2500), ("estorno", -2500)]
    r = vulto_mais_cliente(sa_conn, cliente.id)
    assert (r["saldo"], r["creditos_no_ano"], r["categoria"]) == (0, 0, "bronze")


def test_valor_corrigido_depois_ajusta_a_diferenca(cena):
    c, _, cliente, pedido = cena
    mudar(c, pedido, valor_total=100, status="pago")
    mudar(c, pedido, valor_total=80)
    mudar(c, pedido, valor_total=120)
    assert sum(p for _, p in extrato(c, cliente)) == 120


def test_troca_de_cliente_leva_os_pontos(cena, fab_sa):
    c, _, cliente, pedido = cena
    outro = fab_sa.usuario("cliente")
    mudar(c, pedido, valor_total=90, status="pago")
    mudar(c, pedido, id_cliente=outro.id)
    assert sum(p for _, p in extrato(c, cliente)) == 0
    assert extrato(c, outro) == [("credito", 90)]


def test_venda_antiga_importada_nao_pontua(cena):
    c, loja, cliente, _ = cena
    c.execute(
        "INSERT INTO pedido (numero_pedido, id_loja, id_cliente, id_status_pedido, valor_total, "
        "canal_venda, criado_em) "
        "VALUES ('PD-ANTIGO', %s, %s, %s, 500, 'loja', now() - interval '200 days')",
        (loja, cliente.id, status(c, "pago")),
    )
    assert extrato(c, cliente) == []


def test_pedido_de_funcionario_nao_pontua(fab_sa):
    c, loja = fab_sa.conn, fab_sa.loja()
    atendente = fab_sa.usuario("atendente", loja=loja)
    pedido = fab_sa.pedido(loja=loja, cliente=atendente)
    mudar(c, pedido, canal_venda="loja", valor_total=100, status="pago")
    assert extrato(c, atendente) == []


# ---------- vencimentos: banco e Python dao o mesmo resultado ----------

M = namedtuple("M", "tipo pontos ocorrido_em vence_em id_pedido")


def _cenario(rnd):
    """Movimentos aleatorios em volta do corte da carga (creditos, ajustes e resgates).

    Realistas: o resgate nunca passa dos pontos que ainda valem naquele momento (a plataforma
    limita a saida ao saldo; os casos de divida tem testes proprios).
    """
    momentos = sorted(
        CORTE_DA_CARGA + timedelta(days=rnd.randint(-500, 200), minutes=rnd.randint(0, 999))
        for _ in range(rnd.randint(1, 12))
    )
    eventos, lotes = [], []  # lotes: [vence_em, resta]
    for quando in momentos:
        sorteio = rnd.random()
        if sorteio < 0.5:
            pontos = rnd.randint(1, 900)
            eventos.append(("credito", pontos, quando, quando + ANO, None))
            lotes.append([quando + ANO, pontos])
        elif sorteio < 0.6:
            pontos = rnd.randint(1, 300)
            eventos.append(("ajuste", pontos, quando, None, None))
            lotes.append([None, pontos])
        else:
            validos = [lote for lote in lotes if lote[0] is None or lote[0] > quando]
            falta = min(rnd.randint(1, 600), sum(lote[1] for lote in validos))
            if falta <= 0:
                continue
            eventos.append(("resgate", -falta, quando, None, None))
            for lote in validos:
                usado = min(lote[1], falta)
                lote[1] -= usado
                falta -= usado
    rnd.shuffle(eventos)  # gravados fora de ordem, como pode acontecer na carga
    return eventos, []


@pytest.mark.parametrize("semente", range(25))
def test_vencimentos_do_banco_batem_com_o_python(fab_sa, sa_conn, semente):
    from sqlalchemy import text

    rnd = random.Random(semente)
    c = fab_sa.conn
    cliente = fab_sa.usuario("cliente")
    eventos, _ = _cenario(rnd)
    # Gravadas como a carga grava (origem da carga, fora de ordem): a trava de saldo da plataforma
    # nao entra aqui; o teste confere so a regra de vencimento.
    for tipo, pontos, quando, vence, _ped in eventos:
        c.execute(
            "INSERT INTO movimento_pontos (id_usuario, tipo, pontos, ocorrido_em, vence_em, "
            "descricao, origem) VALUES (%s, %s, %s, %s, %s, 'teste', 'vulto+')",
            (cliente.id, tipo, pontos, quando, vence),
        )
    # "Agora" pode cair antes de movimentacoes ja gravadas: elas nao adiantam vencimento.
    agora = CORTE_DA_CARGA + timedelta(days=rnd.randint(1, 450))
    movimentos = [
        M(*r)
        for r in c.execute(
            "SELECT tipo, pontos, ocorrido_em, vence_em, id_pedido FROM movimento_pontos "
            "WHERE id_usuario = %s ORDER BY ocorrido_em, criado_em, id_movimento",
            (cliente.id,),
        ).fetchall()
    ]
    esperado, _ = calcular(movimentos, agora)

    lancou = sa_conn.execute(
        text("SELECT public.lancar_vencimentos_pontos(CAST(:c AS uuid), :a)"),
        {"c": str(cliente.id), "a": agora},
    ).scalar()
    gravados = c.execute(
        "SELECT pontos, ocorrido_em FROM movimento_pontos WHERE id_usuario = %s "
        "AND tipo = 'vencimento' ORDER BY ocorrido_em",
        (cliente.id,),
    ).fetchall()
    assert gravados == [(v["pontos"], v["ocorrido_em"]) for v in esperado]
    assert lancou == -sum(v["pontos"] for v in esperado)
    # Rodar de novo nao lanca nada.
    assert (
        sa_conn.execute(
            text("SELECT public.lancar_vencimentos_pontos(CAST(:c AS uuid), :a)"),
            {"c": str(cliente.id), "a": agora},
        ).scalar()
        == 0
    )


def test_estorno_sai_do_credito_da_propria_compra(cena):
    from sqlalchemy import text  # noqa: F401

    c, _, cliente, pedido = cena
    # Credito antigo que vence logo depois do corte e uma compra nova cancelada em parte.
    antigo = CORTE_DA_CARGA - ANO + 5 * DIA
    c.execute(
        "INSERT INTO movimento_pontos (id_usuario, tipo, pontos, ocorrido_em, vence_em, descricao) "
        "VALUES (%s, 'credito', 100, %s, %s, 'antigo')",
        (cliente.id, antigo, antigo + ANO),
    )
    mudar(c, pedido, valor_total=200, status="pago")
    mudar(c, pedido, valor_total=150)  # estorno de 50 ligado ao pedido
    c.execute("SELECT public.lancar_vencimentos_pontos(%s, %s)", (cliente.id, antigo + ANO + DIA))
    venc = c.execute(
        "SELECT pontos FROM movimento_pontos WHERE id_usuario = %s AND tipo = 'vencimento'",
        (cliente.id,),
    ).fetchall()
    assert venc == [(-100,)]  # o antigo vence inteiro: o estorno saiu da compra
