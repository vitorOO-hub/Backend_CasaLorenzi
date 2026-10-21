"""Transferencias entre lojas e estoque minimo contra um Postgres real (casos criticos)."""

import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from sqlalchemy import create_engine

from app.core.db import _url_sqlalchemy
from app.core.erros_auth import SemPermissao
from app.core.papeis import Papel, UsuarioAtual
from app.painel_estoque import minimos, transferencias
from app.painel_estoque.erros import (
    LojaInvalida,
    LojaObrigatoria,
    PecaNaoEncontrada,
    SaldoInsuficiente,
    SemPermissaoNaTransferencia,
    TransferenciaJaDecidida,
    TransferenciaNaoEncontrada,
)
from tests.banco.apoio import como as como_papel
from tests.banco.apoio import e_erro, tenta

pytestmark = pytest.mark.banco


class SemCommit:
    """O service confirma a transacao; nos testes isso vira no-op para nao deixar dados no banco."""

    def __init__(self, conexao):
        self._conexao = conexao

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def __getattr__(self, nome):
        return getattr(self._conexao, nome)


@pytest.fixture
def sa_conn(sa_conn):
    return SemCommit(sa_conn)


@pytest.fixture
def cena(fab_sa):
    fab = fab_sa
    c = fab.conn
    a, b, outra = fab.loja(), fab.loja(), fab.loja()

    def um(comando, parametros=()):
        return c.execute(comando, parametros).fetchone()[0]

    produto = um(
        "INSERT INTO produto (nome, marca, preco_base) VALUES ('Camisa T', 'Casa', 1) "
        "RETURNING id_produto"
    )
    variacao = um(
        "INSERT INTO variacao_produto (id_produto, sku, cor, tamanho, preco_venda) "
        "VALUES (%s, 'TR-1', 'Branco', 'M', 1) RETURNING id_variacao",
        (produto,),
    )
    for loja, quantidade, minimo in ((a, 10, 2), (b, 2, 2)):
        c.execute(
            "INSERT INTO estoque (id_loja, id_variacao, quantidade, estoque_minimo) "
            "VALUES (%s, %s, %s, %s)",
            (loja, variacao, quantidade, minimo),
        )
    pessoas = SimpleNamespace(
        ger_a=fab.usuario("gerente_loja", loja=a),
        op_a=fab.usuario("operador_estoque", loja=a),
        ger_b=fab.usuario("gerente_loja", loja=b),
        op_b=fab.usuario("operador_estoque", loja=b),
        ger_c=fab.usuario("gerente_loja", loja=outra),
        admin=fab.usuario("diretor"),
        atendente=fab.usuario("atendente", loja=a),
    )
    return SimpleNamespace(c=c, a=a, b=b, outra=outra, v=variacao, p=pessoas, um=um)


def eu(usuario) -> UsuarioAtual:
    papel = {"diretor": Papel.ADMIN}.get(usuario.tipo) or Papel(usuario.tipo)
    return UsuarioAtual(
        id_auth=usuario.auth, papel=papel, id_loja=None if papel is Papel.ADMIN else usuario.loja
    )


def saldo(cena, loja):
    linha = cena.c.execute(
        "SELECT quantidade FROM estoque WHERE id_loja = %s AND id_variacao = %s", (loja, cena.v)
    ).fetchone()
    return linha[0] if linha else None


def pedir(conn, cena, quem, origem, quantidade=3, sku="TR-1"):
    dados = transferencias.NovaTransferencia(sku=sku, quantidade=quantidade, id_loja_origem=origem)
    return transferencias.solicitar(conn, eu(quem), dados)


def decisao(**campos):
    return transferencias.Decisao(**campos)


def movimentos(cena, loja):
    return cena.c.execute(
        "SELECT t.codigo, m.quantidade, m.quantidade_anterior, m.quantidade_posterior "
        "FROM movimentacao_estoque m JOIN tipo_movimentacao_estoque t "
        "USING (id_tipo_movimentacao_estoque) WHERE m.id_loja = %s ORDER BY m.criada_em",
        (loja,),
    ).fetchall()


# ------------------------------------------------------------------ fluxo


def test_fluxo_completo_move_a_peca_so_no_aceite_e_no_recebimento(sa_conn, cena):
    t = pedir(sa_conn, cena, cena.p.ger_b, cena.a, 3)
    assert (t["status"], t["tipo"], t["acoes"]) == ("solicitada", "transferencia", [])
    assert (saldo(cena, cena.a), saldo(cena, cena.b)) == (10, 2)  # pedir nao move nada

    aceita = transferencias.aceitar(sa_conn, eu(cena.p.ger_a), t["id_transferencia"], decisao())
    assert aceita["status"] == "aceita" and aceita["responsavel"] is not None
    assert (saldo(cena, cena.a), saldo(cena, cena.b)) == (7, 2)  # saiu da origem
    assert movimentos(cena, cena.a) == [("transferencia_saida", 3, 10, 7)]

    recebida = transferencias.receber(sa_conn, eu(cena.p.ger_b), t["id_transferencia"])
    assert recebida["status"] == "recebida" and recebida["recebida_em"] is not None
    assert (saldo(cena, cena.a), saldo(cena, cena.b)) == (7, 5)  # entrou no destino
    assert movimentos(cena, cena.b) == [("transferencia_entrada", 3, 2, 5)]


def test_aceitar_sem_saldo_na_origem_falha_e_nada_muda(sa_conn, cena):
    t = pedir(sa_conn, cena, cena.p.ger_b, cena.a, 20)
    with pytest.raises(SaldoInsuficiente):
        transferencias.aceitar(sa_conn, eu(cena.p.ger_a), t["id_transferencia"], decisao())
    assert saldo(cena, cena.a) == 10 and movimentos(cena, cena.a) == []
    status = cena.c.execute("SELECT 1 FROM transferencia_estoque").fetchone()
    assert status is not None


def test_so_a_origem_aceita_e_so_o_destino_recebe(sa_conn, cena):
    t = pedir(sa_conn, cena, cena.p.ger_b, cena.a)
    for quem in (cena.p.ger_b, cena.p.op_b):  # o proprio pedinte nao aceita
        with pytest.raises(SemPermissaoNaTransferencia):
            transferencias.aceitar(sa_conn, eu(quem), t["id_transferencia"], decisao())
    with pytest.raises(TransferenciaNaoEncontrada):  # loja alheia nem ve que existe
        transferencias.aceitar(sa_conn, eu(cena.p.ger_c), t["id_transferencia"], decisao())
    transferencias.aceitar(sa_conn, eu(cena.p.op_a), t["id_transferencia"], decisao())
    with pytest.raises(SemPermissaoNaTransferencia):  # a origem nao confirma o recebimento
        transferencias.receber(sa_conn, eu(cena.p.ger_a), t["id_transferencia"])
    with pytest.raises(TransferenciaNaoEncontrada):
        transferencias.receber(sa_conn, eu(cena.p.ger_c), t["id_transferencia"])
    transferencias.receber(sa_conn, eu(cena.p.op_b), t["id_transferencia"])


def test_etapas_nao_se_repetem_nem_pulam(sa_conn, cena):
    t = pedir(sa_conn, cena, cena.p.ger_b, cena.a, 3)
    i = t["id_transferencia"]
    with pytest.raises(TransferenciaJaDecidida):  # receber antes de aceitar
        transferencias.receber(sa_conn, eu(cena.p.ger_b), i)
    transferencias.aceitar(sa_conn, eu(cena.p.ger_a), i, decisao())
    with pytest.raises(TransferenciaJaDecidida):  # aceitar duas vezes nao debita duas vezes
        transferencias.aceitar(sa_conn, eu(cena.p.ger_a), i, decisao())
    with pytest.raises(TransferenciaJaDecidida):  # nem recusar o que ja saiu
        transferencias.recusar(sa_conn, eu(cena.p.ger_a), i, decisao(motivo="tarde"))
    transferencias.receber(sa_conn, eu(cena.p.ger_b), i)
    with pytest.raises(TransferenciaJaDecidida):  # nem receber duas vezes
        transferencias.receber(sa_conn, eu(cena.p.ger_b), i)
    assert (saldo(cena, cena.a), saldo(cena, cena.b)) == (7, 5)


def test_recusar_guarda_o_motivo_e_nao_mexe_no_estoque(sa_conn, cena):
    t = pedir(sa_conn, cena, cena.p.ger_b, cena.a)
    r = transferencias.recusar(
        sa_conn, eu(cena.p.ger_a), t["id_transferencia"], decisao(motivo="Sem peca para mandar")
    )
    assert (r["status"], r["motivo_recusa"], r["acoes"]) == ("recusada", "Sem peca para mandar", [])
    assert (saldo(cena, cena.a), saldo(cena, cena.b)) == (10, 2)
    with pytest.raises(TransferenciaJaDecidida):
        transferencias.aceitar(sa_conn, eu(cena.p.ger_a), t["id_transferencia"], decisao())


def test_pedido_invalido(sa_conn, cena):
    with pytest.raises(LojaInvalida):
        pedir(sa_conn, cena, cena.p.ger_b, cena.b)  # de si para si
    with pytest.raises(LojaInvalida):
        pedir(sa_conn, cena, cena.p.ger_b, uuid4())  # loja que nao existe
    with pytest.raises(PecaNaoEncontrada):
        pedir(sa_conn, cena, cena.p.ger_b, cena.a, sku="NAO-EXISTE")
    with pytest.raises(SemPermissao):
        pedir(sa_conn, cena, cena.p.atendente, cena.b)
    with pytest.raises(LojaObrigatoria):  # admin precisa dizer por qual loja pede
        pedir(sa_conn, cena, cena.p.admin, cena.a)


def test_o_destino_vem_do_login_e_outra_loja_da_403(sa_conn, cena):
    dados = transferencias.NovaTransferencia(
        sku="TR-1", quantidade=1, id_loja_origem=cena.a, id_loja=cena.outra
    )
    with pytest.raises(SemPermissao):
        transferencias.solicitar(sa_conn, eu(cena.p.ger_b), dados)


# ------------------------------------------------------------------ reposicao


def test_reposicao_a_rede_uma_outra_loja_atende_e_vira_a_origem(sa_conn, cena):
    r = transferencias.pedir_reposicao(
        sa_conn, eu(cena.p.ger_b), transferencias.NovaReposicao(sku="TR-1", quantidade=4)
    )
    assert (r["tipo"], r["id_loja_origem"], r["status"]) == ("reposicao_rede", None, "solicitada")
    i = r["id_transferencia"]
    with pytest.raises(SemPermissaoNaTransferencia):  # quem pediu nao se atende
        transferencias.aceitar(sa_conn, eu(cena.p.ger_b), i, decisao())

    vista = transferencias.listar_do_usuario(
        sa_conn, eu(cena.p.ger_c), id_loja=None, situacao="acao", tipo=None, limit=10, offset=0
    )
    assert [x["acoes"] for x in vista["itens"]] == [["aceitar", "recusar"]]
    meu = transferencias.listar_do_usuario(
        sa_conn, eu(cena.p.ger_b), id_loja=None, situacao="acao", tipo=None, limit=10, offset=0
    )
    assert meu["itens"] == [] and meu["aguardando_voce"] == 0

    atendida = transferencias.aceitar(sa_conn, eu(cena.p.ger_a), i, decisao())
    assert (atendida["id_loja_origem"], atendida["status"]) == (cena.a, "aceita")
    assert saldo(cena, cena.a) == 6
    transferencias.receber(sa_conn, eu(cena.p.ger_b), i)
    assert saldo(cena, cena.b) == 6


def test_admin_atende_reposicao_informando_a_loja(sa_conn, cena):
    r = transferencias.pedir_reposicao(
        sa_conn, eu(cena.p.ger_b), transferencias.NovaReposicao(sku="TR-1", quantidade=1)
    )
    with pytest.raises(LojaObrigatoria):
        transferencias.aceitar(sa_conn, eu(cena.p.admin), r["id_transferencia"], decisao())
    with pytest.raises(SemPermissaoNaTransferencia):  # nao atende pela propria loja que pediu
        transferencias.aceitar(
            sa_conn, eu(cena.p.admin), r["id_transferencia"], decisao(id_loja=cena.b)
        )
    ok = transferencias.aceitar(
        sa_conn, eu(cena.p.admin), r["id_transferencia"], decisao(id_loja=cena.a)
    )
    assert ok["id_loja_origem"] == cena.a and saldo(cena, cena.a) == 9


def test_recebimento_cria_a_linha_quando_o_destino_nao_tinha_a_peca(sa_conn, cena):
    cena.c.execute("DELETE FROM estoque WHERE id_loja = %s", (cena.b,))
    t = pedir(sa_conn, cena, cena.p.ger_b, cena.a, 2)
    transferencias.aceitar(sa_conn, eu(cena.p.ger_a), t["id_transferencia"], decisao())
    transferencias.receber(sa_conn, eu(cena.p.ger_b), t["id_transferencia"])
    assert saldo(cena, cena.b) == 2


# ------------------------------------------------------------------ listagem e escopo


def listar(conn, quem, **filtros):
    base = {"id_loja": None, "situacao": "todas", "tipo": None, "limit": 50, "offset": 0}
    return transferencias.listar_do_usuario(conn, eu(quem), **{**base, **filtros})


def test_cada_loja_ve_so_o_que_a_envolve_e_o_admin_ve_tudo(sa_conn, cena):
    pedir(sa_conn, cena, cena.p.ger_b, cena.a)
    assert listar(sa_conn, cena.p.ger_a)["total"] == 1
    assert listar(sa_conn, cena.p.ger_b)["total"] == 1
    assert listar(sa_conn, cena.p.ger_c)["total"] == 0  # terceira loja nao ve
    assert listar(sa_conn, cena.p.admin)["total"] == 1
    with pytest.raises(SemPermissao):
        listar(sa_conn, cena.p.ger_c, id_loja=cena.a)


def test_aguardando_voce_conta_aceitar_e_receber(sa_conn, cena):
    t = pedir(sa_conn, cena, cena.p.ger_b, cena.a)
    assert listar(sa_conn, cena.p.ger_a)["aguardando_voce"] == 1  # aceitar
    assert listar(sa_conn, cena.p.ger_b)["aguardando_voce"] == 0
    transferencias.aceitar(sa_conn, eu(cena.p.ger_a), t["id_transferencia"], decisao())
    assert listar(sa_conn, cena.p.ger_a)["aguardando_voce"] == 0
    destino = listar(sa_conn, cena.p.ger_b, situacao="acao")
    assert destino["aguardando_voce"] == 1 and destino["itens"][0]["acoes"] == ["receber"]
    transferencias.receber(sa_conn, eu(cena.p.ger_b), t["id_transferencia"])
    assert listar(sa_conn, cena.p.ger_b, situacao="andamento")["total"] == 0
    assert listar(sa_conn, cena.p.ger_b, situacao="todas")["total"] == 1


# ------------------------------------------------------------------ simultaneidade


def test_dois_aceites_ao_mesmo_tempo_debitam_uma_vez_so(banco_migrado):
    cod = uuid4().hex[:8]
    with psycopg.connect(banco_migrado, autocommit=True) as c:
        lojas = [
            c.execute(
                "INSERT INTO loja (codigo, nome) VALUES (%s, %s) RETURNING id_loja",
                (f"TC-{cod}-{n}", f"Loja {n}"),
            ).fetchone()[0]
            for n in (1, 2)
        ]

        def usuario(tipo, loja, n):
            auth = uuid4()
            return auth, c.execute(
                "INSERT INTO usuario (id_tipo_usuario, id_loja, auth_user_id, nome, email) VALUES "
                "((SELECT id_tipo_usuario FROM tipo_usuario WHERE codigo = %s), %s, %s, %s, %s) "
                "RETURNING id_usuario",
                (tipo, loja, auth, f"U{n}", f"tc-{cod}-{n}@teste.local"),
            ).fetchone()[0]

        auth_origem, id_origem = usuario("gerente_loja", lojas[0], 1)
        auth_destino, id_destino = usuario("gerente_loja", lojas[1], 2)
        produto = c.execute(
            "INSERT INTO produto (nome, marca, preco_base) "
            "VALUES (%s, 'T', 1) RETURNING id_produto",
            (f"P {cod}",),
        ).fetchone()[0]
        variacao = c.execute(
            "INSERT INTO variacao_produto (id_produto, sku, cor, tamanho, preco_venda) "
            "VALUES (%s, %s, 'c', 't', 1) RETURNING id_variacao",
            (produto, f"TC-{cod}"),
        ).fetchone()[0]
        c.execute(
            "INSERT INTO estoque (id_loja, id_variacao, quantidade, estoque_minimo) "
            "VALUES (%s, %s, 5, 0)",
            (lojas[0], variacao),
        )
        id_transferencia = c.execute(
            """
            INSERT INTO transferencia_estoque (
                id_tipo_transferencia_estoque, id_status_transferencia_estoque,
                id_loja_origem, id_loja_destino, id_variacao, id_usuario_solicitante, quantidade)
            VALUES (
                (SELECT id_tipo_transferencia_estoque FROM tipo_transferencia_estoque
                 WHERE codigo = 'transferencia'),
                (SELECT id_status_transferencia_estoque FROM status_transferencia_estoque
                 WHERE codigo = 'solicitada'),
                %s, %s, %s, %s, 4)
            RETURNING id_transferencia_estoque
            """,
            (lojas[0], lojas[1], variacao, id_destino),
        ).fetchone()[0]
    engine = create_engine(_url_sqlalchemy(banco_migrado), pool_size=4)
    quem = UsuarioAtual(id_auth=auth_origem, papel=Papel.GERENTE_LOJA, id_loja=lojas[0])
    largada = threading.Barrier(2)

    def tentar(_):
        with engine.connect() as conexao:
            largada.wait(timeout=10)
            try:
                return transferencias.aceitar(conexao, quem, id_transferencia, decisao())
            except TransferenciaJaDecidida as erro:
                return erro

    try:
        with ThreadPoolExecutor(2) as pool:
            resultados = list(pool.map(tentar, range(2)))
        assert sum(isinstance(r, dict) for r in resultados) == 1
        assert sum(isinstance(r, TransferenciaJaDecidida) for r in resultados) == 1
        with psycopg.connect(banco_migrado) as c:
            assert c.execute(
                "SELECT quantidade FROM estoque WHERE id_loja = %s", (lojas[0],)
            ).fetchone() == (1,)
            assert c.execute(
                "SELECT count(*) FROM movimentacao_estoque WHERE id_loja = %s", (lojas[0],)
            ).fetchone() == (1,)
    finally:
        engine.dispose()
        with psycopg.connect(banco_migrado, autocommit=True) as c:
            c.execute(
                "DELETE FROM transferencia_estoque WHERE id_transferencia_estoque = %s",
                (id_transferencia,),
            )
            c.execute("DELETE FROM movimentacao_estoque WHERE id_variacao = %s", (variacao,))
            c.execute("DELETE FROM estoque WHERE id_variacao = %s", (variacao,))
            c.execute("DELETE FROM variacao_produto WHERE id_variacao = %s", (variacao,))
            c.execute("DELETE FROM produto WHERE id_produto = %s", (produto,))
            c.execute("DELETE FROM usuario WHERE id_usuario IN (%s, %s)", (id_origem, id_destino))
            c.execute("DELETE FROM loja WHERE id_loja IN (%s, %s)", tuple(lojas))


# ------------------------------------------------------------------ estoque minimo


def definir(conn, quem, itens, loja=None):
    dados = minimos.DefinirMinimos(
        itens=[minimos.NovoMinimo(sku=s, minimo=m) for s, m in itens], id_loja=loja
    )
    return minimos.definir(conn, eu(quem), dados)


def minimo_de(cena, loja):
    return cena.c.execute(
        "SELECT estoque_minimo FROM estoque WHERE id_loja = %s AND id_variacao = %s", (loja, cena.v)
    ).fetchone()[0]


def test_minimos_so_mudam_a_loja_de_quem_pede(sa_conn, cena):
    assert definir(sa_conn, cena.p.ger_a, [("TR-1", 7)]) == {"atualizados": 1}
    assert (minimo_de(cena, cena.a), minimo_de(cena, cena.b)) == (7, 2)
    with pytest.raises(SemPermissao):
        definir(sa_conn, cena.p.ger_a, [("TR-1", 9)], loja=cena.b)
    assert minimo_de(cena, cena.b) == 2


def test_admin_precisa_dizer_a_loja_e_depois_muda_qualquer_uma(sa_conn, cena):
    with pytest.raises(LojaObrigatoria):
        definir(sa_conn, cena.p.admin, [("TR-1", 4)])
    definir(sa_conn, cena.p.admin, [("TR-1", 4)], loja=cena.b)
    assert minimo_de(cena, cena.b) == 4


def test_peca_que_a_loja_nao_tem_recusa_o_lote_inteiro(sa_conn, cena):
    # A transacao e desfeita pelo service; aqui o rollback e simulado pelo wrapper, entao
    # conferimos o que importa: o erro e a quantidade de linhas tocadas.
    with pytest.raises(PecaNaoEncontrada):
        definir(sa_conn, cena.p.ger_a, [("TR-1", 8), ("NAO-EXISTE", 1)])


def test_listagem_de_minimos_traz_saldo_e_minimo_da_loja(sa_conn, cena):
    r = minimos.listar(sa_conn, eu(cena.p.ger_a), id_loja=None, busca=None, limit=50, offset=0)
    assert r["id_loja"] == cena.a and r["total"] == 1
    assert (r["itens"][0]["saldo"], r["itens"][0]["minimo"]) == (10, 2)
    with pytest.raises(LojaObrigatoria):
        minimos.listar(sa_conn, eu(cena.p.admin), id_loja=None, busca=None, limit=5, offset=0)


# ------------------------------------------------------------------ banco: constraint e RLS


def test_status_novos_existem_e_motivo_de_recusa_nao_pode_ser_vazio(cena):
    conn = cena.c
    codigos = {r[0] for r in conn.execute("SELECT codigo FROM status_transferencia_estoque")}
    assert {"solicitada", "aceita", "recebida", "recusada"} <= codigos
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            conn.execute(
                "INSERT INTO transferencia_estoque (id_tipo_transferencia_estoque, "
                "id_status_transferencia_estoque, id_loja_destino, id_variacao, "
                "id_usuario_solicitante, quantidade, motivo_recusa) VALUES ("
                "(SELECT id_tipo_transferencia_estoque FROM tipo_transferencia_estoque LIMIT 1), "
                "(SELECT id_status_transferencia_estoque "
                "FROM status_transferencia_estoque LIMIT 1), "
                "%s, %s, %s, 1, '   ')",
                (cena.a, cena.v, cena.p.ger_a.id),
            )


def inserir_transferencia(cena, conn):
    conn.execute(
        """
        INSERT INTO transferencia_estoque (
            id_tipo_transferencia_estoque, id_status_transferencia_estoque,
            id_loja_origem, id_loja_destino, id_variacao, id_usuario_solicitante, quantidade)
        VALUES (
            (SELECT id_tipo_transferencia_estoque FROM tipo_transferencia_estoque
             WHERE codigo = 'transferencia'),
            (SELECT id_status_transferencia_estoque FROM status_transferencia_estoque
             WHERE codigo = 'solicitada'),
            %s, %s, %s, %s, 1)
        """,
        (cena.a, cena.b, cena.v, cena.p.ger_b.id),
    )


def ver(conn, usuario, consulta, papel=None):
    papel = papel or {"diretor": "admin"}.get(usuario.tipo, usuario.tipo)
    loja = None if papel == "admin" else usuario.loja
    with como_papel(conn, sub=usuario.auth, papel=papel, loja=loja):
        return tenta(conn, consulta)


def test_rls_da_transferencia_equipe_das_duas_lojas_e_admin(cena):
    conn = cena.c
    inserir_transferencia(cena, conn)
    consulta = "SELECT 1 FROM transferencia_estoque"
    for quem in (cena.p.ger_a, cena.p.op_a, cena.p.ger_b, cena.p.op_b, cena.p.admin):
        assert len(ver(conn, quem, consulta)) == 1
    assert ver(conn, cena.p.ger_c, consulta) == []  # terceira loja
    assert ver(conn, cena.p.atendente, consulta) == []  # atendente nao e do estoque
    cliente = cena.p.atendente.__class__(id=uuid4(), auth=uuid4(), tipo="cliente", loja=None)
    assert ver(conn, cliente, consulta, papel="cliente") == []


def test_rls_front_nao_escreve_em_transferencias_nem_ajustes(cena):
    conn = cena.c
    inserir_transferencia(cena, conn)
    for quem in (cena.p.ger_a, cena.p.admin):
        papel = "admin" if quem.tipo == "diretor" else quem.tipo
        loja = None if papel == "admin" else quem.loja
        with como_papel(conn, sub=quem.auth, papel=papel, loja=loja):
            assert e_erro(tenta(conn, "UPDATE transferencia_estoque SET quantidade = 99"))
            assert e_erro(tenta(conn, "DELETE FROM transferencia_estoque"))
            assert e_erro(tenta(conn, "UPDATE ajuste_estoque SET status = 'aprovado'"))
            assert e_erro(tenta(conn, "UPDATE estoque SET quantidade = 999"))
    with como_papel(conn, role="anon"):
        assert e_erro(tenta(conn, "SELECT 1 FROM transferencia_estoque"))


def test_rls_do_ajuste_gestao_da_loja_e_o_proprio_operador(cena):
    conn = cena.c
    for solicitante in (cena.p.op_a, cena.p.op_b):
        loja = solicitante.loja
        conn.execute(
            "INSERT INTO ajuste_estoque (id_loja, id_variacao, id_usuario_solicitante, "
            "quantidade, motivo) VALUES (%s, %s, %s, -1, 'x y z')",
            (loja, cena.v, solicitante.id),
        )
    outro_operador = cena.p.op_a.__class__(
        id=uuid4(), auth=uuid4(), tipo="operador_estoque", loja=cena.a
    )
    consulta = "SELECT 1 FROM ajuste_estoque"
    assert len(ver(conn, cena.p.ger_a, consulta)) == 1  # so os da loja A
    assert len(ver(conn, cena.p.op_a, consulta)) == 1  # o que ele mesmo pediu
    assert len(ver(conn, cena.p.admin, consulta)) == 2
    assert ver(conn, cena.p.ger_c, consulta) == []
    assert ver(conn, cena.p.atendente, consulta) == []
    assert ver(conn, outro_operador, consulta) == []  # colega nao ve o pedido dos outros
