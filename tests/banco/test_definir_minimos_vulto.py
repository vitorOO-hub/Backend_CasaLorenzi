"""Script do estoque minimo da Vulto contra um Postgres real."""

import pytest

from scripts import definir_minimos_vulto as script

pytestmark = pytest.mark.banco


def _loja(c, codigo, nome):
    return c.execute(
        "INSERT INTO loja (codigo, nome) VALUES (%s, %s) "
        "ON CONFLICT (codigo) DO UPDATE SET ativa = true RETURNING id_loja, nome",
        (codigo, nome),
    ).fetchone()


def _peca(fab, c, loja, quantidade, minimo=0, categoria="camisa"):
    variacao = fab.variacao()
    c.execute(
        "UPDATE produto SET categoria = %s WHERE id_produto = "
        "(SELECT id_produto FROM variacao_produto WHERE id_variacao = %s)",
        (categoria, variacao),
    )
    c.execute(
        "INSERT INTO estoque (id_loja, id_variacao, quantidade, estoque_minimo) "
        "VALUES (%s, %s, %s, %s)",
        (loja, variacao, quantidade, minimo),
    )
    return variacao


def _minimo(c, loja, variacao):
    return c.execute(
        "SELECT estoque_minimo FROM estoque WHERE id_loja = %s AND id_variacao = %s",
        (loja, variacao),
    ).fetchone()[0]


def test_minimo_1_so_nas_lojas_fisicas_da_vulto_sem_minimo(sa_conn, fab_sa):
    c = fab_sa.conn
    batel, nome_batel = _loja(c, "LOJA-VULTO-BATEL", "vulto batel")
    app, _ = _loja(c, "LOJA-VULTO-APP", "vulto app")
    lorenzi = fab_sa.loja()
    ultima = _peca(fab_sa, c, batel, 1)
    folgada = _peca(fab_sa, c, batel, 4)
    ja_definida = _peca(fab_sa, c, batel, 9, minimo=3)
    sem_cadastro = _peca(fab_sa, c, batel, 0, categoria="pendente_identificacao")
    no_app = _peca(fab_sa, c, app, 0)
    na_lorenzi = _peca(fab_sa, c, lorenzi, 5)

    linhas = {linha["loja"]: linha for linha in script.definir(sa_conn)}

    assert (_minimo(c, batel, ultima), _minimo(c, batel, folgada)) == (1, 1)
    assert _minimo(c, batel, ja_definida) == 3
    assert _minimo(c, batel, sem_cadastro) == 0
    assert (_minimo(c, app, no_app), _minimo(c, lorenzi, na_lorenzi)) == (0, 0)
    assert linhas[nome_batel]["em_alerta"] >= 1
    assert "vulto app" not in linhas
    auditoria = c.execute(
        "SELECT autor_nome, detalhe FROM auditoria WHERE detalhe LIKE %s", (f"%{nome_batel}%",)
    ).fetchall()
    assert auditoria and auditoria[-1][0] == "Sistema"
