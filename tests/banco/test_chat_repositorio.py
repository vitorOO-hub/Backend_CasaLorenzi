"""O chat ao vivo contra um Postgres real: caixa, nao lidas, cursor e regras de resposta."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.chamados.erros import ChamadoFinalizado, ChamadoNaoEncontrado
from app.chat import service
from app.chat.erros import MensagemDeReferenciaInexistente
from app.core.papeis import Papel, UsuarioAtual

pytestmark = pytest.mark.banco

BRT = timezone(timedelta(hours=-3))


def hora(minuto: int) -> datetime:
    return datetime(2026, 10, 7, 10, minuto, tzinfo=BRT)


class SemCommit:
    """O service faz commit (em producao e o que grava). Nos testes vira no-op, senao os dados do
    cenario ficariam no banco e quebrariam os testes seguintes."""

    def __init__(self, conexao):
        self._conexao = conexao

    def commit(self) -> None:
        pass

    def __getattr__(self, nome):
        return getattr(self._conexao, nome)


@pytest.fixture
def sa_conn(sa_conn):
    return SemCommit(sa_conn)


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
    c = fab.conn
    loja_a, loja_b = fab.loja(), fab.loja()
    helena, bruno = fab.usuario("cliente"), fab.usuario("cliente")
    ate_a, ate_a2 = fab.usuario("atendente", loja=loja_a), fab.usuario("atendente", loja=loja_a)
    ger_a, ate_b = fab.usuario("gerente_loja", loja=loja_a), fab.usuario("atendente", loja=loja_b)
    admin = fab.usuario("diretor")

    ids = {}
    ids["k1"] = fab.atendimento(cliente=helena, loja=loja_a, aberto_em=hora(0), assunto="Costura")
    ids["k2"] = fab.atendimento(
        cliente=helena, loja=loja_a, status="em_andamento", aberto_em=hora(1)
    )
    ids["k3"] = fab.atendimento(cliente=helena, loja=loja_a, status="resolvido", aberto_em=hora(2))
    ids["k4"] = fab.atendimento(cliente=bruno, loja=loja_b, aberto_em=hora(3))
    ids["k5"] = fab.atendimento(cliente=bruno, aberto_em=hora(4))  # sem loja, sem mensagens
    c.execute(
        "UPDATE atendimento SET id_usuario_responsavel = %s WHERE id_atendimento = %s",
        (ate_a.id, ids["k2"]),
    )
    msg = {}
    msg["k1a"] = fab.mensagem(
        atendimento=ids["k1"], remetente=helena, texto="oi", enviada_em=hora(10)
    )
    msg["k1b"] = fab.mensagem(
        atendimento=ids["k1"], remetente=helena, texto="alguem ai?", enviada_em=hora(11)
    )
    msg["k2a"] = fab.mensagem(
        atendimento=ids["k2"], remetente=helena, texto="problema", enviada_em=hora(12)
    )
    msg["k2b"] = fab.mensagem(
        atendimento=ids["k2"], remetente=ate_a, texto="vou ver", enviada_em=hora(13)
    )
    fab.mensagem(atendimento=ids["k3"], remetente=helena, texto="antigo", enviada_em=hora(5))
    fab.mensagem(atendimento=ids["k4"], remetente=bruno, texto="outra loja", enviada_em=hora(6))
    return SimpleNamespace(
        ids=ids,
        msg=msg,
        lojas=(loja_a, loja_b),
        helena=helena,
        bruno=bruno,
        ate_a=ate_a,
        ate_a2=ate_a2,
        ger_a=ger_a,
        ate_b=ate_b,
        admin=admin,
    )


def inbox(conn, quem, **filtros):
    _, escopo = contexto(conn, quem)
    base = dict(secao="todas", apenas_nao_lidas=False, limit=50, offset=0)
    return service.listar(conn, escopo, **{**base, **filtros})


def chaves(cenario, itens):
    inverso = {v: k for k, v in cenario.ids.items()}
    return [inverso[i["id_atendimento"]] for i in itens]


# ------------------------------------------------------------------ caixa de conversas


def test_caixa_mostra_so_conversas_abertas_do_escopo(sa_conn, cenario):
    r = inbox(sa_conn, cenario.ate_a)
    assert set(chaves(cenario, r["itens"])) == {
        "k1",
        "k2",
        "k5",
    }  # sem a resolvida e sem a da loja B
    assert r["total"] == 3


def test_ordem_aguardando_resposta_primeiro_depois_a_mais_recente(sa_conn, cenario):
    r = inbox(sa_conn, cenario.ate_a)
    # k1: cliente falou por ultimo (aguardando); k2: a equipe respondeu; k5: sem mensagens
    assert chaves(cenario, r["itens"]) == ["k1", "k2", "k5"]
    assert [i["aguardando_resposta"] for i in r["itens"]] == [True, False, False]


def test_ultima_mensagem_traz_texto_autor_e_hora(sa_conn, cenario):
    itens = {
        k: i
        for k, i in zip(
            chaves(cenario, inbox(sa_conn, cenario.ate_a)["itens"]),
            inbox(sa_conn, cenario.ate_a)["itens"],
            strict=True,
        )
    }
    assert itens["k1"]["ultima_mensagem"]["texto"] == "alguem ai?"
    assert itens["k1"]["ultima_mensagem"]["autor"] == "cliente"
    assert itens["k2"]["ultima_mensagem"]["autor"] == "atendente"
    assert itens["k5"]["ultima_mensagem"] is None


def test_previa_da_ultima_mensagem_e_cortada(sa_conn, fab_sa, cenario):
    fab_sa.mensagem(
        atendimento=cenario.ids["k5"], remetente=cenario.bruno, texto="x" * 500, enviada_em=hora(30)
    )
    previa = next(i for i in inbox(sa_conn, cenario.ate_a)["itens"] if i["ultima_mensagem"])
    assert all(
        len(i["ultima_mensagem"]["texto"]) <= 140
        for i in inbox(sa_conn, cenario.ate_a)["itens"]
        if i["ultima_mensagem"]
    )
    assert previa


@pytest.mark.parametrize(
    ("secao", "esperado"),
    [("fila", {"k1", "k5"}), ("minhas", {"k2"}), ("todas", {"k1", "k2", "k5"})],
)
def test_secoes_da_caixa(sa_conn, cenario, secao, esperado):
    r = inbox(sa_conn, cenario.ate_a, secao=secao)
    assert set(chaves(cenario, r["itens"])) == esperado


def test_minhas_conversas_sao_so_as_que_eu_assumi(sa_conn, cenario):
    assert inbox(sa_conn, cenario.ate_a2, secao="minhas")["itens"] == []


def test_admin_ve_a_rede_inteira(sa_conn, cenario):
    r = inbox(sa_conn, cenario.admin)
    assert set(chaves(cenario, r["itens"])) == {"k1", "k2", "k4", "k5"}


def test_equipe_da_outra_loja_nao_ve_conversas_da_loja_a(sa_conn, cenario):
    r = inbox(sa_conn, cenario.ate_b)
    assert set(chaves(cenario, r["itens"])) == {"k4", "k5"}  # a dela e a sem loja


def test_paginacao_devolve_total_real(sa_conn, cenario):
    pagina = inbox(sa_conn, cenario.ate_a, limit=1, offset=1)
    assert pagina["total"] == 3 and chaves(cenario, pagina["itens"]) == ["k2"]


# ------------------------------------------------------------------ nao lidas


def test_nao_lidas_contam_so_mensagens_do_cliente(sa_conn, cenario):
    itens = dict(
        zip(
            chaves(cenario, inbox(sa_conn, cenario.ate_a)["itens"]),
            inbox(sa_conn, cenario.ate_a)["itens"],
            strict=True,
        )
    )
    assert itens["k1"]["nao_lidas"] == 2
    assert itens["k2"]["nao_lidas"] == 1  # a mensagem da propria equipe nunca conta
    assert itens["k5"]["nao_lidas"] == 0


def test_filtro_so_nao_lidas(sa_conn, cenario):
    r = inbox(sa_conn, cenario.ate_a, apenas_nao_lidas=True)
    assert set(chaves(cenario, r["itens"])) == {"k1", "k2"}


def test_resumo_da_caixa(sa_conn, cenario):
    _, escopo = contexto(sa_conn, cenario.ate_a)
    assert service.resumo(sa_conn, escopo) == {
        "fila": 2,
        "minhas": 1,
        "com_nao_lidas": 2,
        "nao_lidas": 3,
        "aguardando_resposta": 1,
    }


def test_marcar_lido_zera_so_para_quem_leu(sa_conn, cenario):
    _, escopo = contexto(sa_conn, cenario.ate_a)
    assert service.marcar_lido(sa_conn, escopo, cenario.ids["k1"]) == {"nao_lidas": 0}
    lidas = {i["id_atendimento"]: i["nao_lidas"] for i in inbox(sa_conn, cenario.ate_a)["itens"]}
    assert lidas[cenario.ids["k1"]] == 0 and lidas[cenario.ids["k2"]] == 1
    # a colega continua vendo 2 nao lidas: a leitura e individual
    outras = {i["id_atendimento"]: i["nao_lidas"] for i in inbox(sa_conn, cenario.ate_a2)["itens"]}
    assert outras[cenario.ids["k1"]] == 2
    assert service.resumo(sa_conn, escopo)["nao_lidas"] == 1


def test_mensagem_nova_do_cliente_depois_de_ler_volta_a_contar(sa_conn, fab_sa, cenario):
    _, escopo = contexto(sa_conn, cenario.ate_a)
    service.marcar_lido(sa_conn, escopo, cenario.ids["k1"])
    futuro = datetime.now(BRT) + timedelta(minutes=5)
    fab_sa.mensagem(
        atendimento=cenario.ids["k1"], remetente=cenario.helena, texto="e agora?", enviada_em=futuro
    )
    novo = next(
        i
        for i in inbox(sa_conn, cenario.ate_a)["itens"]
        if i["id_atendimento"] == cenario.ids["k1"]
    )
    assert novo["nao_lidas"] == 1


def test_marcar_lido_duas_vezes_nao_volta_no_tempo(sa_conn, fab_sa, cenario):
    _, escopo = contexto(sa_conn, cenario.ate_a)
    service.marcar_lido(sa_conn, escopo, cenario.ids["k1"])
    primeiro = fab_sa.conn.execute("SELECT lida_ate FROM chamado_leitura").fetchone()[0]
    service.marcar_lido(sa_conn, escopo, cenario.ids["k1"])
    segundo = fab_sa.conn.execute("SELECT lida_ate FROM chamado_leitura").fetchone()[0]
    assert segundo >= primeiro
    assert fab_sa.conn.execute("SELECT count(*) FROM chamado_leitura").fetchone()[0] == 1


def test_marcar_lido_em_conversa_de_outra_loja_da_404(sa_conn, cenario):
    _, escopo = contexto(sa_conn, cenario.ate_a)
    with pytest.raises(ChamadoNaoEncontrado):
        service.marcar_lido(sa_conn, escopo, cenario.ids["k4"])


# ------------------------------------------------------------------ sessao


def test_sessao_traz_canal_privado_filtro_e_quem_sou_eu(sa_conn, cenario):
    token, escopo = contexto(sa_conn, cenario.ate_a)
    s = service.sessao(sa_conn, token, escopo, cenario.ids["k1"])
    assert s["topico"] == f"chamado:{cenario.ids['k1']}" and s["canal_privado"] is True
    assert s["filtro_mensagens"] == f"id_atendimento=eq.{cenario.ids['k1']}"
    assert s["eu"]["id_usuario"] == cenario.ate_a.id and s["eu"]["papel"] == "atendente"
    assert s["ultimo_id_mensagem"] == cenario.msg["k1b"] and s["nao_lidas"] == 2


@pytest.mark.parametrize(
    ("quem", "chamado", "pode", "trecho"),
    [
        ("ate_a", "k1", True, None),  # sem responsavel: quem responder assume
        ("ate_a", "k2", True, None),  # e meu
        ("ate_a2", "k2", False, "esta com"),  # e da colega
        ("ger_a", "k2", True, None),  # gestao responde em qualquer um
        ("admin", "k2", True, None),
        ("ate_a", "k3", False, "encerrado"),  # resolvido
    ],
)
def test_quem_pode_responder(sa_conn, cenario, quem, chamado, pode, trecho):
    token, escopo = contexto(sa_conn, getattr(cenario, quem))
    s = service.sessao(sa_conn, token, escopo, cenario.ids[chamado])
    assert s["pode_responder"] is pode
    assert (s["motivo_bloqueio"] is None) is pode
    if trecho:
        assert trecho in s["motivo_bloqueio"]


def test_sessao_de_conversa_de_outra_loja_da_404(sa_conn, cenario):
    token, escopo = contexto(sa_conn, cenario.ate_a)
    with pytest.raises(ChamadoNaoEncontrado):
        service.sessao(sa_conn, token, escopo, cenario.ids["k4"])
    with pytest.raises(ChamadoNaoEncontrado):
        service.sessao(sa_conn, token, escopo, uuid4())


def test_sessao_sem_mensagens_nao_tem_cursor(sa_conn, cenario):
    token, escopo = contexto(sa_conn, cenario.ate_a)
    s = service.sessao(sa_conn, token, escopo, cenario.ids["k5"])
    assert s["ultimo_id_mensagem"] is None and s["nao_lidas"] == 0


# ------------------------------------------------------------------ recuperar mensagens


def textos(r):
    return [m["texto"] for m in r["mensagens"]]


def test_sem_cursor_vem_as_ultimas_em_ordem_cronologica(sa_conn, cenario):
    _, escopo = contexto(sa_conn, cenario.ate_a)
    r = service.mensagens(sa_conn, escopo, cenario.ids["k2"], apos=None, limit=100)
    assert textos(r) == ["problema", "vou ver"]
    assert r["ultimo_id_mensagem"] == cenario.msg["k2b"]
    assert [m["autor"] for m in r["mensagens"]] == ["cliente", "atendente"]


def test_limite_sem_cursor_pega_as_mais_recentes(sa_conn, cenario):
    _, escopo = contexto(sa_conn, cenario.ate_a)
    r = service.mensagens(sa_conn, escopo, cenario.ids["k2"], apos=None, limit=1)
    assert textos(r) == ["vou ver"]


def test_com_cursor_vem_so_o_que_veio_depois(sa_conn, cenario):
    _, escopo = contexto(sa_conn, cenario.ate_a)
    r = service.mensagens(sa_conn, escopo, cenario.ids["k2"], apos=cenario.msg["k2a"], limit=100)
    assert textos(r) == ["vou ver"]
    r = service.mensagens(sa_conn, escopo, cenario.ids["k1"], apos=cenario.msg["k1a"], limit=100)
    assert textos(r) == ["alguem ai?"]


def test_cursor_na_ultima_devolve_vazio_e_mantem_o_cursor(sa_conn, cenario):
    _, escopo = contexto(sa_conn, cenario.ate_a)
    r = service.mensagens(sa_conn, escopo, cenario.ids["k2"], apos=cenario.msg["k2b"], limit=100)
    assert r["mensagens"] == [] and r["ultimo_id_mensagem"] == cenario.msg["k2b"]


def test_mensagens_na_mesma_hora_nao_se_perdem_nem_se_repetem(sa_conn, fab_sa, cenario):
    """Duas mensagens no mesmo instante: o cursor desempata pelo id, sem pular nem duplicar."""
    a = fab_sa.mensagem(
        atendimento=cenario.ids["k5"], remetente=cenario.bruno, texto="A", enviada_em=hora(40)
    )
    b = fab_sa.mensagem(
        atendimento=cenario.ids["k5"], remetente=cenario.bruno, texto="B", enviada_em=hora(40)
    )
    _, escopo = contexto(sa_conn, cenario.ate_a)
    todas = service.mensagens(sa_conn, escopo, cenario.ids["k5"], apos=None, limit=100)["mensagens"]
    primeira, segunda = todas[0]["id_mensagem"], todas[1]["id_mensagem"]
    assert {primeira, segunda} == {a, b}
    depois = service.mensagens(sa_conn, escopo, cenario.ids["k5"], apos=primeira, limit=100)
    assert [m["id_mensagem"] for m in depois["mensagens"]] == [segunda]


def test_cursor_de_outra_conversa_ou_inexistente_da_404(sa_conn, cenario):
    _, escopo = contexto(sa_conn, cenario.ate_a)
    with pytest.raises(MensagemDeReferenciaInexistente):
        service.mensagens(sa_conn, escopo, cenario.ids["k2"], apos=cenario.msg["k1a"], limit=10)
    with pytest.raises(MensagemDeReferenciaInexistente):
        service.mensagens(sa_conn, escopo, cenario.ids["k2"], apos=uuid4(), limit=10)


def test_mensagens_de_conversa_fora_do_escopo_dao_404(sa_conn, cenario):
    _, escopo = contexto(sa_conn, cenario.ate_a)
    with pytest.raises(ChamadoNaoEncontrado):
        service.mensagens(sa_conn, escopo, cenario.ids["k4"], apos=None, limit=10)


# ------------------------------------------------------------------ enviar


def test_enviar_grava_assume_marca_lido_e_usa_o_token_como_remetente(sa_conn, fab_sa, cenario):
    token, escopo = contexto(sa_conn, cenario.ate_a)
    m = service.enviar_mensagem(sa_conn, token, escopo, cenario.ids["k1"], "Ja estou vendo")
    assert m["autor"] == "atendente" and m["texto"] == "Ja estou vendo"
    remetente = fab_sa.conn.execute(
        "SELECT id_usuario_remetente FROM mensagem WHERE id_mensagem = %s", (m["id_mensagem"],)
    ).fetchone()[0]
    assert remetente == cenario.ate_a.id
    s = service.sessao(sa_conn, token, escopo, cenario.ids["k1"])
    assert s["sou_responsavel"] is True and s["status"]["codigo"] == "em_andamento"
    assert s["nao_lidas"] == 0  # quem escreve ja leu tudo


def test_colega_nao_envia_em_conversa_assumida_mas_o_gerente_sim(sa_conn, cenario):
    token, escopo = contexto(sa_conn, cenario.ate_a2)
    with pytest.raises(Exception, match="ja assumiu"):
        service.enviar_mensagem(sa_conn, token, escopo, cenario.ids["k2"], "Posso ajudar?")
    token, escopo = contexto(sa_conn, cenario.ger_a)
    assert service.enviar_mensagem(sa_conn, token, escopo, cenario.ids["k2"], "Acompanhando")[
        "texto"
    ]


def test_nao_envia_em_conversa_resolvida_nem_de_outra_loja(sa_conn, cenario):
    token, escopo = contexto(sa_conn, cenario.ate_a)
    with pytest.raises(ChamadoFinalizado):
        service.enviar_mensagem(sa_conn, token, escopo, cenario.ids["k3"], "Tarde demais")
    with pytest.raises(ChamadoNaoEncontrado):
        service.enviar_mensagem(sa_conn, token, escopo, cenario.ids["k4"], "Intruso")
