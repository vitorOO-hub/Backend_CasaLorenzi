"""A area de chamados contra um Postgres real: SQL, escopo de loja e transicoes de estado."""

import re
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.chamados import repositorio, service
from app.chamados.erros import (
    ChamadoFinalizado,
    ChamadoJaAssumido,
    ChamadoNaoEncontrado,
    ChamadoSemResponsavel,
    SemPermissaoNoChamado,
)
from app.core.papeis import Papel, UsuarioAtual

pytestmark = pytest.mark.banco

BRT = timezone(timedelta(hours=-3))


class SemCommit:
    """O service faz commit (em producao e o que grava). Nos testes o commit vira no-op, senao
    os dados do cenario ficariam no banco e quebrariam os testes seguintes."""

    def __init__(self, conexao):
        self._conexao = conexao

    def commit(self) -> None:
        pass

    def __getattr__(self, nome):
        return getattr(self._conexao, nome)


@pytest.fixture
def sa_conn(sa_conn):
    return SemCommit(sa_conn)


def dia(n: int) -> datetime:
    return datetime(2026, 10, n, 10, 0, tzinfo=BRT)


def como_token(usuario) -> UsuarioAtual:
    papel = {"diretor": Papel.ADMIN}.get(usuario.tipo) or Papel(usuario.tipo)
    return UsuarioAtual(
        id_auth=usuario.auth, papel=papel, id_loja=None if papel is Papel.ADMIN else usuario.loja
    )


def contexto(conexao, usuario, id_loja=None):
    token = como_token(usuario)
    return token, service.montar_escopo(conexao, token, id_loja)


@pytest.fixture
def cenario(fab_sa):
    fab = fab_sa
    loja_a, loja_b = fab.loja(), fab.loja()
    cliente, cliente2 = fab.usuario("cliente"), fab.usuario("cliente")
    fab.conn.execute(
        "UPDATE usuario SET telefone = '11 99999-0000', cidade = 'Sao Paulo, SP' "
        "WHERE id_usuario = %s",
        (cliente.id,),
    )
    ate_a, ate_a2 = fab.usuario("atendente", loja=loja_a), fab.usuario("atendente", loja=loja_a)
    ger_a, ate_b = fab.usuario("gerente_loja", loja=loja_a), fab.usuario("atendente", loja=loja_b)
    admin = fab.usuario("diretor")

    pedido = fab.pedido(loja=loja_a, cliente=cliente)
    item = fab.item_pedido(pedido=pedido)

    ids = {}

    def chamado(nome, **dados):
        ids[nome] = fab.atendimento(**dados)

    chamado(
        "c1",
        cliente=cliente,
        loja=loja_a,
        pedido=pedido,
        prioridade="alta",
        canal="whatsapp",
        categoria="entrega",
        assunto="Costura soltando",
        aberto_em=dia(5),
    )
    chamado(
        "c2",
        cliente=cliente,
        loja=loja_a,
        prioridade="baixa",
        status="em_andamento",
        aberto_em=dia(4),
    )
    chamado(
        "c3", cliente=cliente, loja=loja_a, prioridade="media", status="resolvido", aberto_em=dia(3)
    )
    chamado("c4", cliente=cliente2, loja=loja_b, prioridade="urgente", aberto_em=dia(5))
    chamado("c5", cliente=cliente, prioridade="media", aberto_em=dia(2))  # sem loja
    fab.conn.execute(
        "UPDATE atendimento SET id_usuario_responsavel = %s WHERE id_atendimento = %s",
        (ate_a.id, ids["c2"]),
    )
    fab.conn.execute(
        "INSERT INTO atendimento_item (id_atendimento, id_item_pedido) VALUES (%s, %s)",
        (ids["c1"], item),
    )
    fab.conn.execute(
        "INSERT INTO chamado_anexo (id_atendimento, nome, caminho) "
        "VALUES (%s, 'foto.jpg', 'chamados/foto.jpg')",
        (ids["c1"],),
    )
    fab.mensagem(atendimento=ids["c2"], remetente=cliente, texto="Chegou errado", enviada_em=dia(4))
    fab.mensagem(
        atendimento=ids["c2"],
        remetente=ate_a,
        texto="Vamos resolver",
        enviada_em=dia(4) + timedelta(minutes=5),
    )
    return SimpleNamespace(
        ids=ids,
        lojas=(loja_a, loja_b),
        cliente=cliente,
        ate_a=ate_a,
        ate_a2=ate_a2,
        ger_a=ger_a,
        ate_b=ate_b,
        admin=admin,
        pedido=pedido,
    )


def lista(conn, cenario, quem, **filtros):
    token, escopo = contexto(conn, quem)
    base = dict(
        situacao="abertos",
        responsavel="todos",
        prioridade=None,
        canal=None,
        categoria=None,
        limit=50,
        offset=0,
    )
    return service.listar(conn, escopo, **{**base, **filtros})


def nomes(cenario, itens):
    inverso = {v: k for k, v in cenario.ids.items()}
    return [inverso[i["id_atendimento"]] for i in itens]


# ------------------------------------------------------------------ campos novos


def test_protocolo_nasce_sozinho_no_formato_e_e_unico(fab_sa, cenario):
    protocolos = [r[0] for r in fab_sa.conn.execute("SELECT protocolo FROM atendimento").fetchall()]
    assert all(re.fullmatch(r"AT-\d{4}-\d{4,}", p) for p in protocolos)
    assert len(set(protocolos)) == len(protocolos)


def test_protocolo_informado_e_respeitado_e_repetido_e_recusado(fab_sa, cenario):
    import psycopg

    c = fab_sa.conn
    c.execute(
        "UPDATE atendimento SET protocolo = 'AT-2026-9999' WHERE id_atendimento = %s",
        (cenario.ids["c1"],),
    )
    with pytest.raises(psycopg.errors.UniqueViolation):
        c.execute(
            "UPDATE atendimento SET protocolo = 'AT-2026-9999' WHERE id_atendimento = %s",
            (cenario.ids["c2"],),
        )


def test_cidade_do_cliente_nao_aceita_texto_vazio(fab_sa, cenario):
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation):
        fab_sa.conn.execute(
            "UPDATE usuario SET cidade = '   ' WHERE id_usuario = %s", (cenario.cliente.id,)
        )


# ------------------------------------------------------------------ lista e filtros


def test_atendente_ve_a_propria_loja_e_os_sem_loja_nunca_a_outra(sa_conn, cenario):
    r = lista(sa_conn, cenario, cenario.ate_a, situacao="todos")
    assert set(nomes(cenario, r["itens"])) == {"c1", "c2", "c3", "c5"}
    assert r["total"] == 4


def test_ordem_e_prioridade_alta_primeiro_depois_o_mais_recente(sa_conn, cenario):
    r = lista(sa_conn, cenario, cenario.ate_a)
    assert nomes(cenario, r["itens"]) == ["c1", "c5", "c2"]  # alta, media, baixa


@pytest.mark.parametrize(
    ("filtro", "esperado"),
    [
        ({"situacao": "aberto"}, {"c1", "c5"}),
        ({"situacao": "em_andamento"}, {"c2"}),
        ({"situacao": "resolvido"}, {"c3"}),
        ({"responsavel": "fila"}, {"c1", "c5"}),
        ({"prioridade": "alta"}, {"c1"}),
        ({"canal": "whatsapp"}, {"c1"}),
        ({"categoria": "entrega"}, {"c1"}),
    ],
)
def test_filtros_da_lista(sa_conn, cenario, filtro, esperado):
    r = lista(sa_conn, cenario, cenario.ate_a, **filtro)
    assert set(nomes(cenario, r["itens"])) == esperado


def test_responsavel_eu_mostra_so_o_que_a_pessoa_assumiu(sa_conn, cenario):
    meus = lista(sa_conn, cenario, cenario.ate_a, responsavel="eu")
    assert set(nomes(cenario, meus["itens"])) == {"c2"}
    outros = lista(sa_conn, cenario, cenario.ate_a2, responsavel="eu")
    assert outros["itens"] == []


def test_prioridade_alta_inclui_urgente(sa_conn, cenario):
    r = lista(sa_conn, cenario, cenario.admin, prioridade="alta")
    assert set(nomes(cenario, r["itens"])) == {"c1", "c4"}
    so_urgente = lista(sa_conn, cenario, cenario.admin, prioridade="urgente")
    assert set(nomes(cenario, so_urgente["itens"])) == {"c4"}


def test_paginacao_devolve_total_real(sa_conn, cenario):
    pagina = lista(sa_conn, cenario, cenario.ate_a, limit=1, offset=1)
    assert pagina["total"] == 3
    assert len(pagina["itens"]) == 1
    assert nomes(cenario, pagina["itens"]) == ["c5"]


def test_item_traz_assunto_com_fallback_e_marca_o_responsavel(sa_conn, cenario):
    itens = {nomes(cenario, [i])[0]: i for i in lista(sa_conn, cenario, cenario.ate_a)["itens"]}
    assert itens["c1"]["assunto"] == "Costura soltando"
    assert itens["c2"]["assunto"] == itens["c2"]["categoria"]["nome"]  # sem assunto: a categoria
    assert itens["c2"]["sou_responsavel"] is True and itens["c1"]["sou_responsavel"] is False
    assert itens["c2"]["responsavel_nome"] and itens["c1"]["responsavel_nome"] is None
    assert re.fullmatch(r"AT-\d{4}-\d{4,}", itens["c1"]["protocolo"])


def test_admin_ve_a_rede_e_ao_filtrar_uma_loja_perde_os_sem_loja(sa_conn, cenario):
    rede = lista(sa_conn, cenario, cenario.admin, situacao="todos")
    assert set(nomes(cenario, rede["itens"])) == {"c1", "c2", "c3", "c4", "c5"}
    token, escopo = contexto(sa_conn, cenario.admin, cenario.lojas[0])
    so_a = service.listar(
        sa_conn,
        escopo,
        situacao="todos",
        responsavel="todos",
        prioridade=None,
        canal=None,
        categoria=None,
        limit=50,
        offset=0,
    )
    assert set(nomes(cenario, so_a["itens"])) == {"c1", "c2", "c3"}


def test_filtro_malicioso_nao_vira_sql(sa_conn, cenario):
    r = lista(sa_conn, cenario, cenario.admin, canal="x'; DROP TABLE atendimento; --")
    assert r["itens"] == []
    assert sa_conn.exec_driver_sql("SELECT count(*) FROM atendimento").scalar() >= 5


# ------------------------------------------------------------------ resumo e opcoes


def test_resumo_conta_so_o_escopo_de_quem_pergunta(sa_conn, cenario):
    _, escopo = contexto(sa_conn, cenario.ate_a)
    assert service.resumo(sa_conn, escopo) == {
        "sem_resposta": 2,
        "em_andamento": 1,
        "prioridade_alta": 1,
        "resolvidos": 1,
        "na_fila": 2,
        "meus": 1,
    }
    _, escopo2 = contexto(sa_conn, cenario.ate_a2)
    assert service.resumo(sa_conn, escopo2)["meus"] == 0


def test_opcoes_trazem_so_a_loja_da_equipe_e_todas_para_o_admin(sa_conn, cenario):
    token, escopo = contexto(sa_conn, cenario.ate_a)
    o = service.opcoes(sa_conn, token, escopo)
    assert [loja["id_loja"] for loja in o["lojas"]] == [cenario.lojas[0]]
    assert {s["codigo"] for s in o["status"]} >= {"aberto", "em_andamento", "resolvido"}
    assert len(o["canais"]) >= 5 and len(o["categorias"]) >= 6 and len(o["prioridades"]) == 4
    token, escopo = contexto(sa_conn, cenario.admin)
    assert set(cenario.lojas) <= {
        loja["id_loja"] for loja in service.opcoes(sa_conn, token, escopo)["lojas"]
    }


# ------------------------------------------------------------------ detalhe e conversa


def test_detalhe_traz_cliente_pedido_peca_anexo_e_outros_chamados(sa_conn, cenario):
    token, escopo = contexto(sa_conn, cenario.ate_a)
    d = service.detalhe(sa_conn, token, escopo, cenario.ids["c1"])
    assert d["cliente"]["nome"] and d["cliente"]["email"].endswith("@teste.local")
    assert d["cliente"]["telefone"] == "11 99999-0000" and d["cliente"]["cidade"] == "Sao Paulo, SP"
    assert d["pedido"]["numero_pedido"].startswith("PD-") and d["pedido"]["status"]
    assert len(d["pecas"]) == 1 and d["pecas"][0]["sku"].startswith("SKU-")
    assert [a["nome"] for a in d["anexos"]] == ["foto.jpg"]
    assert {o["protocolo"] for o in d["outros_chamados"]} == {
        r["protocolo"]
        for r in lista(sa_conn, cenario, cenario.ate_a, situacao="todos")["itens"]
        if r["id_atendimento"] != cenario.ids["c1"]
    }


def test_compras_recentes_so_para_a_gestao(sa_conn, cenario):
    token, escopo = contexto(sa_conn, cenario.ate_a)
    assert service.detalhe(sa_conn, token, escopo, cenario.ids["c1"])["compras_recentes"] is None
    token, escopo = contexto(sa_conn, cenario.ger_a)
    compras = service.detalhe(sa_conn, token, escopo, cenario.ids["c1"])["compras_recentes"]
    assert [c["id_pedido"] for c in compras] == [cenario.pedido]


def test_chamado_de_outra_loja_e_inexistente_para_quem_nao_e_dela(sa_conn, cenario):
    token, escopo = contexto(sa_conn, cenario.ate_b)
    with pytest.raises(ChamadoNaoEncontrado):
        service.detalhe(sa_conn, token, escopo, cenario.ids["c1"])
    with pytest.raises(ChamadoNaoEncontrado):
        service.mensagens(sa_conn, escopo, cenario.ids["c1"])


def test_conversa_em_ordem_com_autor_cliente_ou_atendente(sa_conn, cenario):
    _, escopo = contexto(sa_conn, cenario.ate_a)
    conversa = service.mensagens(sa_conn, escopo, cenario.ids["c2"])
    assert [(m["autor"], m["texto"]) for m in conversa] == [
        ("cliente", "Chegou errado"),
        ("atendente", "Vamos resolver"),
    ]


# ------------------------------------------------------------------ responder


def test_primeira_resposta_assume_o_chamado_e_tira_de_aberto(sa_conn, cenario):
    token, escopo = contexto(sa_conn, cenario.ate_a)
    m = service.enviar_mensagem(sa_conn, token, escopo, cenario.ids["c1"], "Ja estou vendo")
    assert m["autor"] == "atendente" and m["texto"] == "Ja estou vendo"
    item = repositorio.obter_item(sa_conn, escopo, cenario.ids["c1"])
    assert item["status"]["codigo"] == "em_andamento" and item["sou_responsavel"] is True


def test_o_remetente_vem_do_token_e_nao_de_quem_o_cliente_diz(sa_conn, fab_sa, cenario):
    token, escopo = contexto(sa_conn, cenario.ate_a)
    m = service.enviar_mensagem(sa_conn, token, escopo, cenario.ids["c1"], "Oi")
    remetente = fab_sa.conn.execute(
        "SELECT id_usuario_remetente FROM mensagem WHERE id_mensagem = %s", (m["id_mensagem"],)
    ).fetchone()[0]
    assert remetente == cenario.ate_a.id


def test_outro_atendente_nao_responde_chamado_assumido_mas_o_gerente_sim(sa_conn, cenario):
    token, escopo = contexto(sa_conn, cenario.ate_a2)
    with pytest.raises(ChamadoJaAssumido, match="ja assumiu"):
        service.enviar_mensagem(sa_conn, token, escopo, cenario.ids["c2"], "Posso ajudar?")
    token, escopo = contexto(sa_conn, cenario.ger_a)
    assert service.enviar_mensagem(sa_conn, token, escopo, cenario.ids["c2"], "Acompanhando")[
        "texto"
    ]
    item = repositorio.obter_item(sa_conn, escopo, cenario.ids["c2"])
    assert item["id_usuario_responsavel"] == cenario.ate_a.id  # o gerente nao toma o chamado


def test_nao_responde_chamado_resolvido(sa_conn, cenario):
    token, escopo = contexto(sa_conn, cenario.ate_a)
    with pytest.raises(ChamadoFinalizado):
        service.enviar_mensagem(sa_conn, token, escopo, cenario.ids["c3"], "Tarde demais")


def test_nao_responde_chamado_de_outra_loja(sa_conn, cenario):
    token, escopo = contexto(sa_conn, cenario.ate_b)
    with pytest.raises(ChamadoNaoEncontrado):
        service.enviar_mensagem(sa_conn, token, escopo, cenario.ids["c1"], "Intruso")


# ------------------------------------------------------------------ assumir e resolver


def test_assumir_define_responsavel_e_status(sa_conn, cenario):
    _, escopo = contexto(sa_conn, cenario.ate_a)
    item = service.assumir(sa_conn, escopo, cenario.ids["c1"])
    assert item["sou_responsavel"] is True and item["status"]["codigo"] == "em_andamento"


def test_assumir_de_novo_diz_quem_ja_assumiu(sa_conn, cenario):
    _, escopo_a = contexto(sa_conn, cenario.ate_a)
    service.assumir(sa_conn, escopo_a, cenario.ids["c1"])
    _, escopo_a2 = contexto(sa_conn, cenario.ate_a2)
    with pytest.raises(ChamadoJaAssumido, match=r"Usuario \d+ ja assumiu"):
        service.assumir(sa_conn, escopo_a2, cenario.ids["c1"])
    with pytest.raises(ChamadoJaAssumido, match="Voce ja assumiu"):
        service.assumir(sa_conn, escopo_a, cenario.ids["c1"])


def test_nao_assume_resolvido_nem_de_outra_loja(sa_conn, cenario):
    _, escopo = contexto(sa_conn, cenario.ate_a)
    with pytest.raises(ChamadoFinalizado):
        service.assumir(sa_conn, escopo, cenario.ids["c3"])
    _, escopo_b = contexto(sa_conn, cenario.ate_b)
    with pytest.raises(ChamadoNaoEncontrado):
        service.assumir(sa_conn, escopo_b, cenario.ids["c1"])


def test_atendente_so_resolve_o_que_assumiu(sa_conn, cenario):
    token, escopo = contexto(sa_conn, cenario.ate_a)
    with pytest.raises(ChamadoSemResponsavel):
        service.resolver(sa_conn, token, escopo, cenario.ids["c1"])
    token2, escopo2 = contexto(sa_conn, cenario.ate_a2)
    with pytest.raises(SemPermissaoNoChamado):
        service.resolver(sa_conn, token2, escopo2, cenario.ids["c2"])


def test_resolver_fecha_o_chamado_e_marca_a_data(sa_conn, fab_sa, cenario):
    token, escopo = contexto(sa_conn, cenario.ate_a)
    item = service.resolver(sa_conn, token, escopo, cenario.ids["c2"])
    assert item["status"]["codigo"] == "resolvido"
    encerrado = fab_sa.conn.execute(
        "SELECT encerrado_em FROM atendimento WHERE id_atendimento = %s", (cenario.ids["c2"],)
    ).fetchone()[0]
    assert encerrado is not None
    with pytest.raises(ChamadoFinalizado):
        service.resolver(sa_conn, token, escopo, cenario.ids["c2"])


def test_gerente_resolve_chamado_de_outra_pessoa_e_sem_responsavel(sa_conn, cenario):
    token, escopo = contexto(sa_conn, cenario.ger_a)
    assert (
        service.resolver(sa_conn, token, escopo, cenario.ids["c2"])["status"]["codigo"]
        == "resolvido"
    )
    assert (
        service.resolver(sa_conn, token, escopo, cenario.ids["c1"])["status"]["codigo"]
        == "resolvido"
    )


def test_cadastro_inativo_nao_passa(sa_conn, fab_sa, cenario):
    from app.chamados.erros import CadastroInativo

    fab_sa.conn.execute(
        "UPDATE usuario SET ativo = false WHERE id_usuario = %s", (cenario.ate_a.id,)
    )
    with pytest.raises(CadastroInativo):
        service.montar_escopo(sa_conn, como_token(cenario.ate_a), None)


# ------------------------------------------------------------------ corrida real


def test_duas_pessoas_assumindo_ao_mesmo_tempo_dao_um_sucesso_e_um_conflito(banco_migrado):
    """Dados confirmados de verdade (duas conexoes), desfeitos no fim."""
    import psycopg
    from sqlalchemy import create_engine

    from app.core.db import _url_sqlalchemy
    from tests.banco.fabrica import Fabrica

    with psycopg.connect(banco_migrado, autocommit=True) as c:
        fab = Fabrica(c)
        loja = fab.loja()
        cliente = fab.usuario("cliente")
        a1, a2 = fab.usuario("atendente", loja=loja), fab.usuario("atendente", loja=loja)
        id_chamado = fab.atendimento(cliente=cliente, loja=loja)

    engine = create_engine(_url_sqlalchemy(banco_migrado))
    resultados, trava = [], threading.Barrier(2)

    def tentar(usuario):
        with engine.connect() as conexao:
            escopo = service.montar_escopo(conexao, como_token(usuario), None)
            trava.wait(timeout=10)
            try:
                service.assumir(conexao, escopo, id_chamado)
                resultados.append("ok")
            except ChamadoJaAssumido:
                resultados.append("conflito")

    try:
        threads = [threading.Thread(target=tentar, args=(u,)) for u in (a1, a2)]
        [t.start() for t in threads]
        [t.join(timeout=20) for t in threads]
        assert sorted(resultados) == ["conflito", "ok"]
    finally:
        engine.dispose()
        with psycopg.connect(banco_migrado, autocommit=True) as c:
            c.execute("DELETE FROM atendimento WHERE id_atendimento = %s", (id_chamado,))
            c.execute(
                "DELETE FROM usuario WHERE id_usuario = ANY(%s)", ([cliente.id, a1.id, a2.id],)
            )
            c.execute("DELETE FROM loja WHERE id_loja = %s", (loja,))


def test_uuid_aleatorio_nao_existe(sa_conn, cenario):
    token, escopo = contexto(sa_conn, cenario.ate_a)
    with pytest.raises(ChamadoNaoEncontrado):
        service.detalhe(sa_conn, token, escopo, uuid4())
