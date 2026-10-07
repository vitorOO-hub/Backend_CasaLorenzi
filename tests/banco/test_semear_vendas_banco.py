"""O script de vendas de exemplo gravado num Postgres real: triggers, FKs e as telas do gerente."""

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.gerencia import repositorio
from app.gerencia.repositorio import Filtro

pytestmark = pytest.mark.banco

CAMINHO = Path(__file__).resolve().parents[2] / "scripts" / "semear_vendas.py"
_spec = importlib.util.spec_from_file_location("semear_vendas_banco", CAMINHO)
semear_vendas = importlib.util.module_from_spec(_spec)
sys.modules["semear_vendas_banco"] = semear_vendas
_spec.loader.exec_module(semear_vendas)

AGORA = datetime(2026, 10, 7, 15, 0, tzinfo=timezone(timedelta(hours=-3)))


def base_com_equipe(conn, fab):
    """A loja base com equipe, como fica depois de criar_contas.py."""
    loja = conn.execute(
        "INSERT INTO loja (codigo, nome) VALUES ('LOJA-CENTRO', 'Casa Lorenzi Centro') "
        "RETURNING id_loja"
    ).fetchone()[0]
    for tipo in ("gerente_loja", "operador_estoque", "atendente"):
        fab.usuario(tipo, loja=loja)
    return loja


@pytest.fixture
def banco_semeado(conn, fab):
    loja = base_com_equipe(conn, fab)
    return loja, semear_vendas.semear(conn, agora=AGORA)


def test_o_script_grava_tudo_sem_quebrar_nenhuma_regra_do_banco(conn, banco_semeado):
    _, plano = banco_semeado
    contagem = {
        tabela: conn.execute(f"SELECT count(*) FROM {tabela}").fetchone()[0]  # nosec B608
        for tabela in ("pedido", "item_pedido", "pagamento", "movimentacao_estoque", "estoque")
    }
    assert contagem["pedido"] == len(plano.pedidos) > 1000
    assert contagem["item_pedido"] == len(plano.itens)
    assert contagem["pagamento"] == len(plano.pagamentos)
    assert contagem["movimentacao_estoque"] == len(plano.movimentos)
    assert contagem["estoque"] == len(plano.estoque)


def test_rodar_de_novo_nao_duplica(conn, banco_semeado):
    antes = conn.execute("SELECT count(*) FROM pedido").fetchone()[0]
    assert semear_vendas.semear(conn, agora=AGORA) is None
    assert conn.execute("SELECT count(*) FROM pedido").fetchone()[0] == antes


def test_cria_as_lojas_a_equipe_e_os_clientes(conn, banco_semeado):
    codigos = {r[0] for r in conn.execute("SELECT codigo FROM loja").fetchall()}
    assert {"LOJA-CENTRO", "LOJA-BARRA", "LOJA-SAVASSI"} <= codigos
    gerentes = conn.execute(
        "SELECT count(*) FROM usuario u JOIN loja l USING (id_loja) "
        "JOIN tipo_usuario t USING (id_tipo_usuario) "
        "WHERE t.codigo = 'gerente_loja' AND l.codigo IN ('LOJA-BARRA', 'LOJA-SAVASSI')"
    ).fetchone()[0]
    assert gerentes == 2
    clientes = conn.execute(
        "SELECT count(*), count(auth_user_id), count(documento) FROM usuario u "
        "JOIN tipo_usuario t USING (id_tipo_usuario) WHERE t.codigo = 'cliente'"
    ).fetchone()
    # Ficticios: nenhum tem login (auth_user_id) nem documento.
    assert clientes == (semear_vendas.QUANTIDADE_DE_CLIENTES, 0, 0)


def test_o_estoque_de_cada_peca_e_a_soma_das_movimentacoes(conn, banco_semeado):
    divergentes = conn.execute(
        """
        SELECT count(*) FROM estoque e
        WHERE e.quantidade <> COALESCE((
            SELECT sum(m.quantidade * t.sinal)
            FROM movimentacao_estoque m
            JOIN tipo_movimentacao_estoque t
                ON t.id_tipo_movimentacao_estoque = m.id_tipo_movimentacao_estoque
            WHERE m.id_loja = e.id_loja AND m.id_variacao = e.id_variacao
        ), 0)
        """
    ).fetchone()[0]
    assert divergentes == 0
    assert conn.execute("SELECT count(*) FROM estoque WHERE quantidade < 0").fetchone()[0] == 0


def test_valor_do_pedido_e_itens_mais_frete(conn, banco_semeado):
    divergentes = conn.execute(
        """
        SELECT count(*) FROM pedido p
        WHERE p.numero_pedido LIKE 'SD-%'
          AND p.valor_total <> p.valor_frete + (
              SELECT sum(i.valor_total) FROM item_pedido i WHERE i.id_pedido = p.id_pedido)
        """
    ).fetchone()[0]
    assert divergentes == 0
    sem_itens = conn.execute(
        "SELECT count(*) FROM pedido p WHERE NOT EXISTS "
        "(SELECT 1 FROM item_pedido i WHERE i.id_pedido = p.id_pedido)"
    ).fetchone()[0]
    assert sem_itens == 0


def test_pagamento_vale_o_total_do_pedido(conn, banco_semeado):
    divergentes = conn.execute(
        "SELECT count(*) FROM pagamento g JOIN pedido p USING (id_pedido) "
        "WHERE g.valor <> p.valor_total"
    ).fetchone()[0]
    assert divergentes == 0


def test_as_telas_do_gerente_enxergam_os_dados(sa_conn, fab_sa):
    loja = base_com_equipe(fab_sa.conn, fab_sa)
    semear_vendas.semear(fab_sa.conn, agora=AGORA)
    conexao = sa_conn
    fim = AGORA.date()
    inicio = fim - timedelta(days=29)
    r = repositorio.resumo(conexao, Filtro(loja), inicio, fim)
    assert r["pedidos"] > 30 and float(r["faturamento"]) > 10_000
    assert r["pedidos_online"] > 0 and float(r["faturamento_online"]) < float(r["faturamento"])
    anterior = repositorio.resumo(
        conexao, Filtro(loja), inicio - timedelta(days=30), inicio - timedelta(days=1)
    )
    assert anterior["pedidos"] > 0  # ha com o que comparar
    ano = repositorio.resumo(conexao, Filtro(loja), fim - timedelta(days=364), fim)
    assert ano["pedidos"] > r["pedidos"] * 6
    assert len(repositorio.pecas_mais_vendidas(conexao, Filtro(loja), inicio, fim, limite=6)) == 6
    semana = repositorio.movimento_semana(conexao, Filtro(loja), inicio, fim)
    assert sum(s["pedidos"] for s in semana) == r["pedidos"]
    total, itens = repositorio.reposicao(conexao, Filtro(loja), limite=6)
    assert (
        total >= 1
        and itens
        and itens[0]["situacao"] in ("esgotada", "abaixo_do_minimo", "cobertura_curta")
    )
    assert repositorio.ajustes_para_aprovar(conexao, Filtro(loja)) == 3
    assert repositorio.transferencias_aguardando(conexao, Filtro(loja)) == 3
