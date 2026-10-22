"""Pontos Vulto+ do cliente (saldo, categoria do ano e extrato), contra um Postgres real."""

import pytest

from app.cliente import repositorio

pytestmark = pytest.mark.banco


def movimento(conn, cliente, tipo, pontos, quando="now()"):
    conn.execute(
        "INSERT INTO movimento_pontos (id_usuario, tipo, pontos, ocorrido_em, descricao) "  # nosec B608
        f"VALUES (%s, %s, %s, {quando}, 'teste')",
        (cliente, tipo, pontos),
    )


def test_saldo_e_a_soma_e_a_categoria_vem_dos_creditos_do_ano(sa_conn, fab_sa):
    cliente = fab_sa.usuario("cliente").id
    c = fab_sa.conn
    movimento(c, cliente, "credito", 1500)
    movimento(c, cliente, "credito", 900)
    movimento(c, cliente, "resgate", -400)
    # Credito de outro ano soma no saldo, mas nao conta para a categoria.
    movimento(c, cliente, "credito", 9000, "now() - interval '2 years'")
    movimento(c, cliente, "vencimento", -9000, "now() - interval '1 year'")
    r = repositorio.vulto_mais_cliente(sa_conn, cliente)
    assert r["saldo"] == 2000
    assert (r["categoria"], r["creditos_no_ano"]) == ("prata", 2400)
    assert (r["proxima_categoria"], r["faltam_para_proxima"]) == ("ouro", 2600)
    # now() e o mesmo na transacao do teste: confere o conteudo, nao a ordem dos empates.
    assert sorted(m["pontos"] for m in r["extrato"]) == [-9000, -400, 900, 1500, 9000]


def test_cliente_sem_pontos_e_bronze_com_saldo_zero(sa_conn, fab_sa):
    r = repositorio.vulto_mais_cliente(sa_conn, fab_sa.usuario("cliente").id)
    assert (r["saldo"], r["categoria"], r["extrato"]) == (0, "bronze", [])
    assert (r["proxima_categoria"], r["faltam_para_proxima"]) == ("prata", 2000)
