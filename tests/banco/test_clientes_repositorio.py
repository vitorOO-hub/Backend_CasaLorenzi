"""A area de clientes contra um Postgres real: escopo de loja, secoes, busca e privacidade."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.chamados import service as chamados
from app.clientes import service
from app.clientes.erros import ClienteNaoEncontrado
from app.core.papeis import Papel, UsuarioAtual

pytestmark = pytest.mark.banco

BRT = timezone(timedelta(hours=-3))


def dia(n: int) -> datetime:
    return datetime(2026, 10, n, 10, 0, tzinfo=BRT)


def como_token(usuario) -> UsuarioAtual:
    papel = {"diretor": Papel.ADMIN}.get(usuario.tipo) or Papel(usuario.tipo)
    return UsuarioAtual(
        id_auth=usuario.auth, papel=papel, id_loja=None if papel is Papel.ADMIN else usuario.loja
    )


def contexto(conexao, usuario, id_loja=None):
    token = como_token(usuario)
    return token, chamados.montar_escopo(conexao, token, id_loja)


@pytest.fixture
def cenario(fab_sa):
    fab = fab_sa
    c = fab.conn
    loja_a, loja_b = fab.loja(), fab.loja()
    helena, bruno, caio, zeca, vazio = (fab.usuario("cliente") for _ in range(5))
    for usuario, nome, tel in [
        (helena, "Helena Vasconcelos", "11 98844-2210"),
        (bruno, "Bruno Teixeira", "21 99120-8845"),
        (caio, "Caio 100% Silva", None),
        (zeca, "Zeca Andrade", "31 97000-1111"),
        (vazio, "Zilda Sem Historico", None),
    ]:
        c.execute(
            "UPDATE usuario SET nome = %s, telefone = %s, cidade = 'Sao Paulo, SP' "
            "WHERE id_usuario = %s",
            (nome, tel, usuario.id),
        )
    ate_a, ate_a2 = fab.usuario("atendente", loja=loja_a), fab.usuario("atendente", loja=loja_a)
    ger_a, ate_b = fab.usuario("gerente_loja", loja=loja_a), fab.usuario("atendente", loja=loja_b)
    admin = fab.usuario("diretor")

    def pedido(loja, cliente, valor, status="criado"):
        id_pedido = fab.pedido(loja=loja, cliente=cliente)
        c.execute(
            "UPDATE pedido SET valor_total = %s, id_status_pedido = "
            "(SELECT id_status_pedido FROM status_pedido WHERE codigo = %s) WHERE id_pedido = %s",
            (valor, status, id_pedido),
        )
        return id_pedido

    pedido(loja_a, helena, 100)
    pedido(loja_a, helena, 50, "cancelado")  # nao conta como compra
    pedido(loja_b, helena, 900)  # outra loja: fora do escopo do gerente A
    pedido(loja_b, bruno, 70)

    ids = {}
    ids["h1"] = fab.atendimento(cliente=helena, loja=loja_a, aberto_em=dia(5), assunto="Costura")
    ids["h2"] = fab.atendimento(cliente=helena, loja=loja_a, status="resolvido", aberto_em=dia(3))
    ids["h3"] = fab.atendimento(cliente=helena, loja=loja_b, aberto_em=dia(4))
    ids["b1"] = fab.atendimento(cliente=bruno, loja=loja_b, aberto_em=dia(5))
    ids["z1"] = fab.atendimento(cliente=zeca, aberto_em=dia(2))  # sem loja
    c.execute(
        "UPDATE atendimento SET id_usuario_responsavel = %s WHERE id_atendimento = %s",
        (ate_a.id, ids["h1"]),
    )
    return SimpleNamespace(
        lojas=(loja_a, loja_b),
        ids=ids,
        helena=helena,
        bruno=bruno,
        caio=caio,
        zeca=zeca,
        vazio=vazio,
        ate_a=ate_a,
        ate_a2=ate_a2,
        ger_a=ger_a,
        ate_b=ate_b,
        admin=admin,
    )


def lista(conn, quem, id_loja=None, **filtros):
    token, escopo = contexto(conn, quem, id_loja)
    base = dict(busca=None, secao="todos", limit=50, offset=0)
    return service.listar(conn, token, escopo, **{**base, **filtros})


def nomes(itens):
    return [i["nome"] for i in itens]


# ------------------------------------------------------------------ escopo


def test_atendente_ve_so_clientes_com_pedido_ou_chamado_no_escopo(sa_conn, cenario):
    r = lista(sa_conn, cenario.ate_a)
    # Helena (pedido e chamados na loja A) e Zeca (chamado sem loja);
    # nao Bruno (so loja B) nem a Zilda (sem historico)
    assert set(nomes(r["itens"])) == {"Helena Vasconcelos", "Zeca Andrade"}
    assert r["total"] == 2


def test_equipe_de_outra_loja_nao_ve_clientes_da_loja_a(sa_conn, cenario):
    r = lista(sa_conn, cenario.ate_b)
    assert set(nomes(r["itens"])) == {"Helena Vasconcelos", "Bruno Teixeira", "Zeca Andrade"}
    # Helena aparece por causa do pedido e do chamado na loja B, mas so conta o que e da loja B
    helena = next(i for i in r["itens"] if i["nome"].startswith("Helena"))
    assert helena["total_chamados"] == 2 - 1  # h3 (loja B) + sem os da A; h2 e h1 nao contam
    assert helena["chamados_em_aberto"] == 1


def test_admin_ve_todos_os_clientes_inclusive_sem_historico(sa_conn, cenario):
    r = lista(sa_conn, cenario.admin)
    assert "Zilda Sem Historico" in nomes(r["itens"])
    assert r["total"] >= 5


def test_admin_filtrando_uma_loja_ve_so_quem_tem_historico_nela(sa_conn, cenario):
    r = lista(sa_conn, cenario.admin, id_loja=cenario.lojas[1])
    assert set(nomes(r["itens"])) == {"Helena Vasconcelos", "Bruno Teixeira"}


# ------------------------------------------------------------------ privacidade das compras


def test_atendente_nao_recebe_compras_nem_valores(sa_conn, cenario):
    for item in lista(sa_conn, cenario.ate_a)["itens"]:
        assert item["compras"] is None and item["total_gasto"] is None


def test_gerente_ve_compras_da_propria_loja_sem_contar_cancelados(sa_conn, cenario):
    r = lista(sa_conn, cenario.ger_a)
    helena = next(i for i in r["itens"] if i["nome"].startswith("Helena"))
    assert helena["compras"] == 1 and helena["total_gasto"] == Decimal(
        "100"
    )  # o de 900 e da loja B


def test_admin_soma_a_rede_inteira(sa_conn, cenario):
    r = lista(sa_conn, cenario.admin)
    helena = next(i for i in r["itens"] if i["nome"].startswith("Helena"))
    assert helena["compras"] == 2 and helena["total_gasto"] == Decimal("1000")


def test_o_banco_nem_calcula_valores_para_o_atendente(sa_conn, cenario):
    """A conta so e feita com ver_compras: nao basta o service esconder o campo."""
    from app.clientes import repositorio

    _, escopo = contexto(sa_conn, cenario.ate_a)
    _, itens = repositorio.listar(
        sa_conn, escopo, ver_compras=False, busca=None, secao="todos", limit=10, offset=0
    )
    assert all(i["compras"] is None and i["total_gasto"] is None for i in itens)


# ------------------------------------------------------------------ secoes, busca, ordem


def test_secao_com_chamados_em_aberto(sa_conn, cenario):
    r = lista(sa_conn, cenario.ate_a, secao="com_aberto")
    assert set(nomes(r["itens"])) == {"Helena Vasconcelos", "Zeca Andrade"}


def test_secao_meus_clientes_so_os_que_eu_assumi(sa_conn, cenario):
    assert nomes(lista(sa_conn, cenario.ate_a, secao="meus")["itens"]) == ["Helena Vasconcelos"]
    assert lista(sa_conn, cenario.ate_a2, secao="meus")["itens"] == []


def test_ordem_chamados_em_aberto_primeiro_depois_nome(sa_conn, cenario):
    r = lista(sa_conn, cenario.admin)
    abertos = [i["chamados_em_aberto"] for i in r["itens"]]
    assert abertos == sorted(abertos, reverse=True)


@pytest.mark.parametrize("termo", ["helena", "HELENA", "vasconc", "98844", "teste.local"])
def test_busca_por_nome_telefone_ou_email_sem_diferenciar_maiusculas(sa_conn, cenario, termo):
    r = lista(sa_conn, cenario.admin, busca=termo)
    assert any(n.startswith("Helena") for n in nomes(r["itens"]))


def test_busca_trata_coringa_digitado_como_letra(sa_conn, cenario):
    assert nomes(lista(sa_conn, cenario.admin, busca="100%")["itens"]) == ["Caio 100% Silva"]
    assert lista(sa_conn, cenario.admin, busca="%")["total"] == 1  # so quem tem '%' no nome
    assert lista(sa_conn, cenario.admin, busca="_")["total"] == 0


def test_busca_maliciosa_nao_vira_sql(sa_conn, cenario):
    r = lista(sa_conn, cenario.admin, busca="x'; DROP TABLE usuario; --")
    assert r["itens"] == []
    assert sa_conn.exec_driver_sql("SELECT count(*) FROM usuario").scalar() >= 5


def test_paginacao_devolve_total_real(sa_conn, cenario):
    pagina = lista(sa_conn, cenario.admin, limit=2, offset=2)
    assert pagina["total"] >= 5 and len(pagina["itens"]) == 2


def test_nunca_lista_equipe_como_cliente(sa_conn, cenario):
    equipe = {
        cenario.ate_a.id,
        cenario.ate_a2.id,
        cenario.ger_a.id,
        cenario.ate_b.id,
        cenario.admin.id,
    }
    r = lista(sa_conn, cenario.admin, limit=100)
    ids = {i["id_cliente"] for i in r["itens"]}
    assert not (ids & equipe)
    assert len(ids) == r["total"]


# ------------------------------------------------------------------ ficha


def test_ficha_do_atendente_tem_contato_e_chamados_mas_nao_compras(sa_conn, cenario):
    token, escopo = contexto(sa_conn, cenario.ate_a)
    f = service.ficha(sa_conn, token, escopo, cenario.helena.id)
    assert (
        f["cliente"]["nome"] == "Helena Vasconcelos" and f["cliente"]["telefone"] == "11 98844-2210"
    )
    assert f["cliente"]["cidade"] == "Sao Paulo, SP"
    assert "documento" not in f["cliente"]
    assert f["compras"] is None
    assert f["resumo"] == {
        "chamados": 2,
        "chamados_em_aberto": 1,
        "compras": None,
        "total_gasto": None,
        "ticket_medio": None,
    }
    assert {c["id_atendimento"] for c in f["chamados"]} == {cenario.ids["h1"], cenario.ids["h2"]}
    assert f["chamados"][0]["id_atendimento"] == cenario.ids["h1"]  # mais recente primeiro


def test_ficha_do_gerente_traz_compras_so_da_loja_e_ticket_medio(sa_conn, cenario):
    token, escopo = contexto(sa_conn, cenario.ger_a)
    f = service.ficha(sa_conn, token, escopo, cenario.helena.id)
    assert [c["valor_total"] for c in f["compras"]].count(Decimal("900")) == 0
    assert {c["status"]["codigo"] for c in f["compras"]} == {
        "criado",
        "cancelado",
    }  # lista tudo da loja
    assert f["resumo"]["compras"] == 1 and f["resumo"]["total_gasto"] == Decimal("100")
    assert f["resumo"]["ticket_medio"] == Decimal("100.00")


def test_ficha_do_admin_soma_a_rede(sa_conn, cenario):
    token, escopo = contexto(sa_conn, cenario.admin)
    f = service.ficha(sa_conn, token, escopo, cenario.helena.id)
    assert f["resumo"]["compras"] == 2 and f["resumo"]["ticket_medio"] == Decimal("500.00")
    assert len(f["compras"]) == 3  # as duas da loja A (uma cancelada) e a da loja B
    assert len({c["loja_nome"] for c in f["compras"]}) == 2


def test_ficha_sem_compras_tem_ticket_zero(sa_conn, cenario):
    token, escopo = contexto(sa_conn, cenario.admin)
    f = service.ficha(sa_conn, token, escopo, cenario.vazio.id)
    assert f["resumo"]["compras"] == 0 and f["resumo"]["ticket_medio"] == Decimal("0.00")
    assert f["chamados"] == []


def test_cliente_fora_do_escopo_e_inexistente_para_a_equipe_da_outra_loja(sa_conn, cenario):
    token, escopo = contexto(sa_conn, cenario.ate_b)
    with pytest.raises(ClienteNaoEncontrado):
        service.ficha(sa_conn, token, escopo, cenario.vazio.id)  # sem historico na loja B
    with pytest.raises(ClienteNaoEncontrado):
        service.ficha(sa_conn, token, escopo, uuid4())


def test_ficha_so_mostra_chamados_do_escopo(sa_conn, cenario):
    token, escopo = contexto(sa_conn, cenario.ate_b)
    f = service.ficha(sa_conn, token, escopo, cenario.helena.id)
    assert {c["id_atendimento"] for c in f["chamados"]} == {cenario.ids["h3"]}


def test_equipe_nao_abre_ficha_de_outro_tipo_de_usuario(sa_conn, cenario):
    token, escopo = contexto(sa_conn, cenario.admin)
    with pytest.raises(ClienteNaoEncontrado):
        service.ficha(sa_conn, token, escopo, cenario.ate_a.id)  # e atendente, nao cliente
