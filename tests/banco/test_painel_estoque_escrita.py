"""Escrita do estoque (entrada, saida e ajustes) contra um Postgres real."""

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
from app.painel_estoque import service, service_escrita
from app.painel_estoque.erros import (
    AjusteJaDecidido,
    AjusteNaoEncontrado,
    LojaObrigatoria,
    PecaNaoEncontrada,
    SaldoInsuficiente,
    SemDiferenca,
)
from app.painel_estoque.repositorio import FiltroMovimentacoes

pytestmark = pytest.mark.banco


class SemCommit:
    """O service confirma a transacao (e o que grava em producao). Nos testes vira no-op, senao os
    dados do cenario ficariam no banco e quebrariam os testes seguintes."""

    def __init__(self, conexao):
        self._conexao = conexao

    def commit(self) -> None:
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
    loja_a, loja_b = fab.loja(), fab.loja()

    def um(comando, parametros=()):
        return c.execute(comando, parametros).fetchone()[0]

    produto = um(
        "INSERT INTO produto (nome, marca, categoria, preco_base) "
        "VALUES ('Camisa Teste', 'Casa Lorenzi', 'Camisas', 100) RETURNING id_produto"
    )

    def variacao(sku, ativa=True):
        return um(
            "INSERT INTO variacao_produto (id_produto, sku, cor, tamanho, preco_venda, ativa) "
            "VALUES (%s, %s, 'Branco', %s, 100, %s) RETURNING id_variacao",
            (produto, sku, sku, ativa),
        )

    v = SimpleNamespace(
        com_saldo=variacao("SKU-5"), sem_linha=variacao("SKU-SEM"), inativa=variacao("SKU-X", False)
    )
    c.execute(
        "INSERT INTO estoque (id_loja, id_variacao, quantidade, estoque_minimo) "
        "VALUES (%s, %s, 5, 2)",
        (loja_a, v.com_saldo),
    )
    c.execute(
        "INSERT INTO estoque (id_loja, id_variacao, quantidade, estoque_minimo) "
        "VALUES (%s, %s, 9, 2)",
        (loja_b, v.com_saldo),
    )
    pessoas = SimpleNamespace(
        operador=fab.usuario("operador_estoque", loja=loja_a),
        outro_operador=fab.usuario("operador_estoque", loja=loja_a),
        gerente=fab.usuario("gerente_loja", loja=loja_a),
        gerente_b=fab.usuario("gerente_loja", loja=loja_b),
        operador_b=fab.usuario("operador_estoque", loja=loja_b),
        atendente=fab.usuario("atendente", loja=loja_a),
        admin=fab.usuario("diretor"),
    )
    return SimpleNamespace(c=c, a=loja_a, b=loja_b, v=v, p=pessoas, um=um)


def como(usuario) -> UsuarioAtual:
    papel = {"diretor": Papel.ADMIN}.get(usuario.tipo) or Papel(usuario.tipo)
    return UsuarioAtual(
        id_auth=usuario.auth, papel=papel, id_loja=None if papel is Papel.ADMIN else usuario.loja
    )


def saldo_de(cena, loja, variacao):
    linha = cena.c.execute(
        "SELECT quantidade FROM estoque WHERE id_loja = %s AND id_variacao = %s", (loja, variacao)
    ).fetchone()
    return linha[0] if linha else None


def movimentar(conn, cena, quem, tipo, quantidade, *, sku="SKU-5", loja=None, motivo="Recebimento"):
    return service_escrita.registrar_movimentacao(
        conn, como(quem), id_loja=loja, sku=sku, tipo=tipo, quantidade=quantidade, motivo=motivo
    )


# ------------------------------------------------------------------ entrada e saida


def test_entrada_soma_ao_saldo_e_lanca_a_movimentacao(sa_conn, cena):
    m = movimentar(sa_conn, cena, cena.p.operador, "entrada", 3, motivo="Recebimento de fornecedor")
    assert saldo_de(cena, cena.a, cena.v.com_saldo) == 8
    assert (m["tipo_codigo"], m["grupo"], m["quantidade"]) == ("entrada", "entrada", 3)
    assert (m["quantidade_anterior"], m["quantidade_posterior"]) == (5, 8)
    assert m["motivo"] == "Recebimento de fornecedor" and m["sku"] == "SKU-5"
    assert m["id_loja"] == cena.a


def test_saida_tira_do_saldo_e_volta_com_sinal_negativo(sa_conn, cena):
    m = movimentar(sa_conn, cena, cena.p.operador, "saida", 2, motivo="Avaria")
    assert saldo_de(cena, cena.a, cena.v.com_saldo) == 3
    assert (m["tipo_codigo"], m["grupo"], m["quantidade"]) == ("saida", "saida", -2)
    assert (m["quantidade_anterior"], m["quantidade_posterior"]) == (5, 3)


def test_saida_de_todo_o_saldo_e_permitida(sa_conn, cena):
    movimentar(sa_conn, cena, cena.p.operador, "saida", 5)
    assert saldo_de(cena, cena.a, cena.v.com_saldo) == 0


def test_saida_maior_que_o_saldo_e_recusada_sem_gravar_nada(sa_conn, cena):
    with pytest.raises(SaldoInsuficiente) as erro:
        movimentar(sa_conn, cena, cena.p.operador, "saida", 6)
    assert "5 unidade" in erro.value.detalhe and erro.value.status_code == 409
    assert saldo_de(cena, cena.a, cena.v.com_saldo) == 5
    assert cena.c.execute("SELECT count(*) FROM movimentacao_estoque").fetchone()[0] == 0


def test_o_responsavel_e_quem_esta_logado(sa_conn, cena):
    movimentar(sa_conn, cena, cena.p.operador, "entrada", 1)
    movimentar(sa_conn, cena, cena.p.gerente, "entrada", 1)
    donos = {
        r[0]
        for r in cena.c.execute(
            "SELECT id_usuario_responsavel FROM movimentacao_estoque"
        ).fetchall()
    }
    assert donos == {cena.p.operador.id, cena.p.gerente.id}


def test_primeira_entrada_numa_loja_cria_a_linha_do_estoque(sa_conn, cena):
    assert saldo_de(cena, cena.a, cena.v.sem_linha) is None
    movimentar(sa_conn, cena, cena.p.operador, "entrada", 4, sku="SKU-SEM")
    assert saldo_de(cena, cena.a, cena.v.sem_linha) == 4
    minimo = cena.c.execute(
        "SELECT estoque_minimo FROM estoque WHERE id_loja = %s AND id_variacao = %s",
        (cena.a, cena.v.sem_linha),
    ).fetchone()[0]
    assert minimo == 0


def test_saida_de_peca_que_a_loja_nao_tem_e_saldo_insuficiente(sa_conn, cena):
    with pytest.raises(SaldoInsuficiente):
        movimentar(sa_conn, cena, cena.p.operador, "saida", 1, sku="SKU-SEM")
    assert saldo_de(cena, cena.a, cena.v.sem_linha) is None


@pytest.mark.parametrize("sku", ["NAO-EXISTE", "SKU-X", "' OR 1=1 --"])
def test_peca_inexistente_ou_inativa_da_404(sa_conn, cena, sku):
    with pytest.raises(PecaNaoEncontrada):
        movimentar(sa_conn, cena, cena.p.operador, "entrada", 1, sku=sku)


def test_produto_inativo_tambem_nao_recebe_movimentacao(sa_conn, cena):
    cena.c.execute("UPDATE produto SET ativo = false")
    with pytest.raises(PecaNaoEncontrada):
        movimentar(sa_conn, cena, cena.p.operador, "entrada", 1)


def test_quem_e_de_loja_nao_mexe_na_estoque_de_outra(sa_conn, cena):
    with pytest.raises(SemPermissao):
        movimentar(sa_conn, cena, cena.p.operador, "saida", 1, loja=cena.b)
    assert saldo_de(cena, cena.b, cena.v.com_saldo) == 9
    # Repetir a propria loja e aceito.
    movimentar(sa_conn, cena, cena.p.operador, "saida", 1, loja=cena.a)


def test_a_loja_do_gerente_vem_do_token(sa_conn, cena):
    movimentar(sa_conn, cena, cena.p.gerente_b, "saida", 4)
    assert saldo_de(cena, cena.b, cena.v.com_saldo) == 5
    assert saldo_de(cena, cena.a, cena.v.com_saldo) == 5


def test_admin_precisa_dizer_a_loja(sa_conn, cena):
    with pytest.raises(LojaObrigatoria):
        movimentar(sa_conn, cena, cena.p.admin, "entrada", 1)
    movimentar(sa_conn, cena, cena.p.admin, "entrada", 1, loja=cena.b)
    assert saldo_de(cena, cena.b, cena.v.com_saldo) == 10


def test_atendente_e_conta_sem_cadastro_nao_movimentam(sa_conn, cena):
    with pytest.raises(SemPermissao):
        movimentar(sa_conn, cena, cena.p.atendente, "entrada", 1)
    fantasma = UsuarioAtual(id_auth=uuid4(), papel=Papel.OPERADOR_ESTOQUE, id_loja=cena.a)
    with pytest.raises(SemPermissao):
        service_escrita.registrar_movimentacao(
            sa_conn,
            fantasma,
            id_loja=None,
            sku="SKU-5",
            tipo="entrada",
            quantidade=1,
            motivo="Teste",
        )
    assert saldo_de(cena, cena.a, cena.v.com_saldo) == 5


def test_o_saldo_sempre_fecha_com_a_soma_das_movimentacoes(sa_conn, cena):
    cena.c.execute("DELETE FROM movimentacao_estoque")
    for tipo, quantidade in (("entrada", 7), ("saida", 3), ("saida", 2), ("entrada", 1)):
        movimentar(sa_conn, cena, cena.p.operador, tipo, quantidade)
    soma = cena.c.execute(
        "SELECT sum(m.quantidade * t.sinal) FROM movimentacao_estoque m "
        "JOIN tipo_movimentacao_estoque t USING (id_tipo_movimentacao_estoque)"
    ).fetchone()[0]
    assert saldo_de(cena, cena.a, cena.v.com_saldo) == 5 + soma == 8


def test_o_operador_enxerga_no_historico_o_que_acabou_de_registrar(sa_conn, cena):
    movimentar(sa_conn, cena, cena.p.operador, "entrada", 2)
    movimentar(sa_conn, cena, cena.p.outro_operador, "entrada", 3)
    operador = como(cena.p.operador)
    filtro = service.filtro_de_movimentacoes(
        sa_conn, operador, id_loja=cena.a, grupo=None, sku=None, de=None, ate=None
    )
    itens = service.montar_movimentacoes(sa_conn, filtro, limit=10, offset=0)["itens"]
    assert [i["quantidade"] for i in itens] == [2]


# ------------------------------------------------------------------ ajustes: pedido


def pedir(conn, cena, quem, contado, *, sku="SKU-5", loja=None, motivo="Contagem do inventario"):
    return service_escrita.solicitar_ajuste(
        conn, como(quem), id_loja=loja, sku=sku, quantidade_contada=contado, motivo=motivo
    )


def test_pedido_guarda_a_diferenca_e_nao_mexe_no_saldo(sa_conn, cena):
    a = pedir(sa_conn, cena, cena.p.operador, 2)
    assert (a["quantidade"], a["saldo_atual"], a["status"]) == (-3, 5, "pendente")
    assert (a["decisor"], a["decidido_em"], a["motivo_recusa"]) == (None, None, None)
    assert a["solicitante"].startswith("Usuario") and a["sku"] == "SKU-5"
    assert saldo_de(cena, cena.a, cena.v.com_saldo) == 5
    assert cena.c.execute("SELECT count(*) FROM movimentacao_estoque").fetchone()[0] == 0


def test_contagem_maior_gera_diferenca_positiva(sa_conn, cena):
    assert pedir(sa_conn, cena, cena.p.operador, 12)["quantidade"] == 7


def test_contagem_igual_ao_saldo_nao_e_ajuste(sa_conn, cena):
    with pytest.raises(SemDiferenca):
        pedir(sa_conn, cena, cena.p.operador, 5)


def test_peca_sem_linha_conta_como_saldo_zero(sa_conn, cena):
    a = pedir(sa_conn, cena, cena.p.operador, 3, sku="SKU-SEM")
    assert (a["quantidade"], a["saldo_atual"]) == (3, 0)
    with pytest.raises(SemDiferenca):
        pedir(sa_conn, cena, cena.p.operador, 0, sku="SKU-SEM")


def test_pedido_de_peca_inexistente_e_de_outra_loja(sa_conn, cena):
    with pytest.raises(PecaNaoEncontrada):
        pedir(sa_conn, cena, cena.p.operador, 1, sku="NAO-EXISTE")
    with pytest.raises(SemPermissao):
        pedir(sa_conn, cena, cena.p.operador, 1, loja=cena.b)
    with pytest.raises(LojaObrigatoria):
        pedir(sa_conn, cena, cena.p.admin, 1)
    assert pedir(sa_conn, cena, cena.p.admin, 1, loja=cena.b)["id_loja"] == cena.b


def listar(conn, quem, **filtros):
    base = {"id_loja": None, "status": None, "limit": 50, "offset": 0}
    return service_escrita.listar_ajustes(conn, como(quem), **{**base, **filtros})


def test_operador_ve_so_os_proprios_pedidos_e_a_gestao_ve_os_da_loja(sa_conn, cena):
    pedir(sa_conn, cena, cena.p.operador, 1)
    pedir(sa_conn, cena, cena.p.outro_operador, 2)
    pedir(sa_conn, cena, cena.p.operador_b, 1)
    assert listar(sa_conn, cena.p.operador)["total"] == 1
    assert listar(sa_conn, cena.p.outro_operador)["total"] == 1
    gerente = listar(sa_conn, cena.p.gerente)
    assert (gerente["total"], gerente["pendentes"]) == (2, 2)
    assert {i["id_loja"] for i in gerente["itens"]} == {cena.a}
    assert listar(sa_conn, cena.p.admin)["total"] == 3
    assert listar(sa_conn, cena.p.admin, id_loja=cena.b)["total"] == 1


def test_filtro_de_situacao_e_contador_de_pendentes(sa_conn, cena):
    primeiro = pedir(sa_conn, cena, cena.p.operador, 1)
    pedir(sa_conn, cena, cena.p.operador, 2)
    service_escrita.aprovar_ajuste(sa_conn, como(cena.p.gerente), primeiro["id_ajuste"])
    todos = listar(sa_conn, cena.p.gerente)
    assert (todos["total"], todos["pendentes"]) == (2, 1)
    assert listar(sa_conn, cena.p.gerente, status="pendente")["total"] == 1
    assert [i["status"] for i in listar(sa_conn, cena.p.gerente, status="decididos")["itens"]] == [
        "aprovado"
    ]
    # O contador de pendentes nao depende do filtro da lista.
    assert listar(sa_conn, cena.p.gerente, status="aprovado")["pendentes"] == 1


# ------------------------------------------------------------------ ajustes: decisao


def aprovar(conn, quem, ajuste):
    return service_escrita.aprovar_ajuste(conn, como(quem), ajuste["id_ajuste"])


def test_aprovar_aplica_a_diferenca_e_registra_a_movimentacao(sa_conn, cena):
    pedido = pedir(sa_conn, cena, cena.p.operador, 2, motivo="Peca danificada")
    a = aprovar(sa_conn, cena.p.gerente, pedido)
    assert saldo_de(cena, cena.a, cena.v.com_saldo) == 2
    assert (a["status"], a["decisor"] is not None, a["decidido_em"] is not None) == (
        "aprovado",
        True,
        True,
    )
    mov = cena.c.execute(
        "SELECT t.codigo, m.quantidade, m.quantidade_anterior, m.quantidade_posterior, "
        "m.motivo, m.id_usuario_responsavel FROM movimentacao_estoque m "
        "JOIN tipo_movimentacao_estoque t USING (id_tipo_movimentacao_estoque)"
    ).fetchall()
    assert mov == [
        ("ajuste_negativo", 3, 5, 2, "Ajuste aprovado: Peca danificada", cena.p.operador.id)
    ]


def test_ajuste_positivo_vira_ajuste_positivo(sa_conn, cena):
    aprovar(sa_conn, cena.p.gerente, pedir(sa_conn, cena, cena.p.operador, 9))
    assert saldo_de(cena, cena.a, cena.v.com_saldo) == 9
    tipo = cena.c.execute(
        "SELECT t.codigo FROM movimentacao_estoque m "
        "JOIN tipo_movimentacao_estoque t USING (id_tipo_movimentacao_estoque)"
    ).fetchone()[0]
    assert tipo == "ajuste_positivo"


def test_aprovar_ajuste_positivo_de_peca_sem_linha_cria_a_linha(sa_conn, cena):
    aprovar(sa_conn, cena.p.gerente, pedir(sa_conn, cena, cena.p.operador, 3, sku="SKU-SEM"))
    assert saldo_de(cena, cena.a, cena.v.sem_linha) == 3


def test_aprovar_duas_vezes_aplica_uma_so(sa_conn, cena):
    a = pedir(sa_conn, cena, cena.p.operador, 1)
    aprovar(sa_conn, cena.p.gerente, a)
    with pytest.raises(AjusteJaDecidido):
        aprovar(sa_conn, cena.p.gerente, a)
    assert saldo_de(cena, cena.a, cena.v.com_saldo) == 1
    assert cena.c.execute("SELECT count(*) FROM movimentacao_estoque").fetchone()[0] == 1


def test_se_o_saldo_mudou_e_a_diferenca_nao_cabe_mais_a_aprovacao_falha(sa_conn, cena):
    a = pedir(sa_conn, cena, cena.p.operador, 0)  # -5
    movimentar(sa_conn, cena, cena.p.operador, "saida", 3)  # sobram 2
    with pytest.raises(SaldoInsuficiente):
        aprovar(sa_conn, cena.p.gerente, a)
    assert saldo_de(cena, cena.a, cena.v.com_saldo) == 2
    status = cena.c.execute("SELECT status FROM ajuste_estoque").fetchone()[0]
    assert status == "pendente"


def test_recusar_guarda_o_motivo_e_nao_mexe_no_estoque(sa_conn, cena):
    a = pedir(sa_conn, cena, cena.p.operador, 1)
    r = service_escrita.recusar_ajuste(
        sa_conn, como(cena.p.gerente), a["id_ajuste"], "Nao bate com a nota"
    )
    assert (r["status"], r["motivo_recusa"]) == ("rejeitado", "Nao bate com a nota")
    assert r["decisor"] is not None and r["decidido_em"] is not None
    assert saldo_de(cena, cena.a, cena.v.com_saldo) == 5
    assert cena.c.execute("SELECT count(*) FROM movimentacao_estoque").fetchone()[0] == 0


def test_ajuste_decidido_nao_decide_de_novo(sa_conn, cena):
    a = pedir(sa_conn, cena, cena.p.operador, 1)
    service_escrita.recusar_ajuste(sa_conn, como(cena.p.gerente), a["id_ajuste"], "Recusado")
    with pytest.raises(AjusteJaDecidido):
        aprovar(sa_conn, cena.p.gerente, a)
    with pytest.raises(AjusteJaDecidido):
        service_escrita.recusar_ajuste(sa_conn, como(cena.p.gerente), a["id_ajuste"], "De novo")


def test_gerente_nao_decide_ajuste_de_outra_loja_mas_o_admin_decide(sa_conn, cena):
    a = pedir(sa_conn, cena, cena.p.operador_b, 1, loja=None)  # loja B
    assert a["id_loja"] == cena.b
    with pytest.raises(AjusteNaoEncontrado):
        aprovar(sa_conn, cena.p.gerente, a)
    assert saldo_de(cena, cena.b, cena.v.com_saldo) == 9
    aprovar(sa_conn, cena.p.admin, a)
    assert saldo_de(cena, cena.b, cena.v.com_saldo) == 1


def test_operador_atendente_e_ajuste_inexistente_nao_decidem(sa_conn, cena):
    a = pedir(sa_conn, cena, cena.p.operador, 1)
    for quem in (cena.p.operador, cena.p.atendente):
        with pytest.raises(SemPermissao):
            aprovar(sa_conn, quem, a)
    with pytest.raises(AjusteNaoEncontrado):
        service_escrita.aprovar_ajuste(sa_conn, como(cena.p.gerente), uuid4())
    assert listar(sa_conn, cena.p.gerente, status="pendente")["total"] == 1


# ------------------------------------------------------------------ banco


def test_motivo_da_recusa_so_existe_em_ajuste_recusado(cena):
    c = cena.c
    base = (cena.a, cena.v.com_saldo, cena.p.operador.id)
    inserir = (
        "INSERT INTO ajuste_estoque (id_loja, id_variacao, id_usuario_solicitante, "
        "id_usuario_decisor, quantidade, motivo, status, decidido_em, motivo_recusa) "
        "VALUES (%s, %s, %s, %s, -1, 'x y z', %s, %s, %s)"
    )
    agora = "2026-10-07T12:00:00Z"
    decisor = cena.p.gerente.id
    for status, decidor, quando, recusa in (
        ("rejeitado", decisor, agora, None),
        ("rejeitado", decisor, agora, "   "),
        ("pendente", None, None, "algo"),
        ("aprovado", decisor, agora, "algo"),
    ):
        with pytest.raises(psycopg.errors.CheckViolation):
            with c.transaction():
                c.execute(inserir, (*base, decidor, status, quando, recusa))
    with c.transaction():
        c.execute(inserir, (*base, decisor, "rejeitado", agora, "Nao bate"))


# ------------------------------------------------------------------ simultaneidade


def test_duas_saidas_ao_mesmo_tempo_nao_estouram_o_saldo(banco_migrado):
    """Duas pessoas tiram a ultima peca juntas: so uma consegue, e o saldo nunca fica negativo."""
    cod = uuid4().hex[:8]
    with psycopg.connect(banco_migrado, autocommit=True) as c:
        loja = c.execute(
            "INSERT INTO loja (codigo, nome) VALUES (%s, 'Loja concorrencia') RETURNING id_loja",
            (f"CONC-{cod}",),
        ).fetchone()[0]
        auth = uuid4()
        usuario = c.execute(
            "INSERT INTO usuario (id_tipo_usuario, id_loja, auth_user_id, nome, email) VALUES "
            "((SELECT id_tipo_usuario FROM tipo_usuario WHERE codigo = 'operador_estoque'), "
            "%s, %s, 'Operador Conc', %s) RETURNING id_usuario",
            (loja, auth, f"conc-{cod}@teste.local"),
        ).fetchone()[0]
        produto = c.execute(
            "INSERT INTO produto (nome, marca, preco_base) "
            "VALUES (%s, 'Conc', 1) RETURNING id_produto",
            (f"Produto {cod}",),
        ).fetchone()[0]
        variacao = c.execute(
            "INSERT INTO variacao_produto (id_produto, sku, cor, tamanho, preco_venda) "
            "VALUES (%s, %s, 'c', 't', 1) RETURNING id_variacao",
            (produto, f"CONC-{cod}"),
        ).fetchone()[0]
        c.execute(
            "INSERT INTO estoque (id_loja, id_variacao, quantidade, estoque_minimo) "
            "VALUES (%s, %s, 1, 0)",
            (loja, variacao),
        )
    engine = create_engine(_url_sqlalchemy(banco_migrado), pool_size=4)
    quem = UsuarioAtual(id_auth=auth, papel=Papel.OPERADOR_ESTOQUE, id_loja=loja)
    largada = threading.Barrier(2)

    def tentar(_):
        with engine.connect() as conexao:
            largada.wait(timeout=10)
            try:
                return service_escrita.registrar_movimentacao(
                    conexao,
                    quem,
                    id_loja=None,
                    sku=f"CONC-{cod}",
                    tipo="saida",
                    quantidade=1,
                    motivo="Venda em loja",
                )
            except SaldoInsuficiente as erro:
                return erro

    try:
        with ThreadPoolExecutor(2) as pool:
            resultados = list(pool.map(tentar, range(2)))
        deu_certo = [r for r in resultados if isinstance(r, dict)]
        recusadas = [r for r in resultados if isinstance(r, SaldoInsuficiente)]
        assert len(deu_certo) == 1 and len(recusadas) == 1
        assert "0 unidade" in recusadas[0].detalhe  # a segunda viu o saldo que a primeira confirmou
        with psycopg.connect(banco_migrado) as c:
            saldo = c.execute(
                "SELECT quantidade FROM estoque WHERE id_loja = %s", (loja,)
            ).fetchone()[0]
            movimentos = c.execute(
                "SELECT count(*) FROM movimentacao_estoque WHERE id_loja = %s", (loja,)
            ).fetchone()[0]
        assert (saldo, movimentos) == (0, 1)
    finally:
        engine.dispose()
        with psycopg.connect(banco_migrado, autocommit=True) as c:
            c.execute("DELETE FROM movimentacao_estoque WHERE id_loja = %s", (loja,))
            c.execute("DELETE FROM estoque WHERE id_loja = %s", (loja,))
            c.execute("DELETE FROM variacao_produto WHERE id_variacao = %s", (variacao,))
            c.execute("DELETE FROM produto WHERE id_produto = %s", (produto,))
            c.execute("DELETE FROM usuario WHERE id_usuario = %s", (usuario,))
            c.execute("DELETE FROM loja WHERE id_loja = %s", (loja,))


def test_o_filtro_do_historico_continua_enxergando_a_linha_criada(sa_conn, cena):
    m = movimentar(sa_conn, cena, cena.p.gerente, "entrada", 1)
    achada = service.montar_movimentacoes(
        sa_conn, FiltroMovimentacoes(id_movimentacao=m["id_movimentacao"]), limit=5, offset=0
    )
    assert achada["total"] == 1
