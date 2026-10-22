"""Vencimento de pontos Vulto+ lancado na leitura (ficha do painel e portal), contra um Postgres
real: grava a linha de vencimento uma vez so e avisa o que vence em 30 dias."""

from datetime import timedelta

import pytest
from sqlalchemy import text

from app.chamados import service as chamados
from app.cliente import service as portal
from app.cliente.vencimento_pontos import CORTE_DA_CARGA
from app.clientes import service
from app.core.papeis import Papel, UsuarioAtual

pytestmark = pytest.mark.banco

ANO = timedelta(days=365)
# Lote que venceu um minuto depois da data de referencia da carga: a carga nao o lancou.
ENTRADA_VENCIDA = CORTE_DA_CARGA - ANO + timedelta(minutes=1)


@pytest.fixture
def cliente(fab_sa):
    c = fab_sa.conn
    cli = fab_sa.usuario("cliente")
    c.execute(
        "INSERT INTO movimento_pontos (id_usuario, tipo, pontos, ocorrido_em, vence_em, descricao) "
        "VALUES (%s, 'credito', 300, %s, %s, 'compra antiga'), "
        "       (%s, 'credito', 200, now() - interval '355 days', "
        "        now() - interval '355 days' + interval '365 days', 'compra recente')",
        (cli.id, ENTRADA_VENCIDA, ENTRADA_VENCIDA + ANO, cli.id),
    )
    return cli


def vencimentos(conexao, id_cliente):
    return (
        conexao.execute(
            text(
                "SELECT pontos FROM movimento_pontos WHERE id_usuario = :c AND tipo = 'vencimento'"
            ),
            {"c": str(id_cliente)},
        )
        .scalars()
        .all()
    )


def ficha(conexao, fab_sa, id_cliente):
    admin = fab_sa.usuario("diretor")
    token = UsuarioAtual(id_auth=admin.auth, papel=Papel.ADMIN, id_loja=None)
    escopo = chamados.montar_escopo(conexao, token, None)
    return service.vulto_mais(conexao, token, escopo, id_cliente)


def test_ficha_lanca_o_vencimento_e_avisa_o_proximo(sa_conn, fab_sa, cliente):
    r = ficha(sa_conn, fab_sa, cliente.id)
    assert r["saldo"] == 200
    assert any(m["tipo"] == "vencimento" and m["pontos"] == -300 for m in r["extrato"])
    assert r["pontos_a_vencer"] == 200
    assert [v["pontos"] for v in r["proximos_vencimentos"]] == [200]
    assert vencimentos(sa_conn, cliente.id) == [-300]


def test_ler_de_novo_nao_lanca_em_dobro(sa_conn, fab_sa, cliente):
    ficha(sa_conn, fab_sa, cliente.id)
    assert ficha(sa_conn, fab_sa, cliente.id)["saldo"] == 200
    assert vencimentos(sa_conn, cliente.id) == [-300]


def test_portal_do_cliente_tambem_lanca(sa_conn, cliente):
    token = UsuarioAtual(id_auth=cliente.auth, papel=None, id_loja=None)
    r = portal.obter_vulto_mais(sa_conn, token)
    assert (r["saldo"], r["pontos_a_vencer"]) == (200, 200)
    assert vencimentos(sa_conn, cliente.id) == [-300]


def test_cliente_sem_pontos_nao_ganha_linha(sa_conn, fab_sa):
    cli = fab_sa.usuario("cliente")
    r = ficha(sa_conn, fab_sa, cli.id)
    assert (r["saldo"], r["pontos_a_vencer"], r["proximos_vencimentos"]) == (0, 0, [])
