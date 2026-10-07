"""O SQL do dashboard contra um Postgres real, com o schema e as migrations aplicados."""

from datetime import UTC, date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.core.erros_auth import SemPermissao
from app.core.papeis import Papel, UsuarioAtual
from app.dashboard import service
from app.dashboard.repositorio import Filtro

pytestmark = pytest.mark.banco

BRT = timezone(timedelta(hours=-3))
INICIO, FIM = date(2026, 10, 1), date(2026, 10, 7)


def em(dia: int, hora: int, minuto: int = 0, mes: int = 10) -> datetime:
    return datetime(2026, mes, dia, hora, minuto, tzinfo=BRT)


def usuario_atual(usuario) -> UsuarioAtual:
    papel = {"diretor": Papel.ADMIN}.get(usuario.tipo) or Papel(usuario.tipo)
    return UsuarioAtual(
        id_auth=usuario.auth,
        papel=papel,
        id_loja=None if papel is Papel.ADMIN else usuario.loja,
    )


@pytest.fixture
def cenario(fab_sa):
    fab = fab_sa
    loja_a, loja_b = fab.loja(), fab.loja()
    cliente = fab.usuario("cliente")
    atendente_a = fab.usuario("atendente", loja=loja_a)
    atendente_b = fab.usuario("atendente", loja=loja_b)
    admin = fab.usuario("diretor")

    def chamado(nome, **dados):
        return nome, fab.atendimento(cliente=cliente, **dados)

    ids = dict(
        [
            # 23:30 de Sao Paulo ja e o dia seguinte em UTC: tem de contar em 02/10.
            chamado(
                "a1",
                loja=loja_a,
                canal="whatsapp",
                categoria="entrega",
                prioridade="alta",
                aberto_em=em(2, 23, 30),
            ),
            chamado(
                "a2",
                loja=loja_a,
                canal="email",
                categoria="pedido",
                prioridade="baixa",
                status="resolvido",
                aberto_em=em(3, 10),
                assunto="Defeito na costura",
            ),
            chamado(
                "a3",
                loja=loja_b,
                canal="whatsapp",
                categoria="troca_devolucao",
                prioridade="media",
                status="em_andamento",
                aberto_em=em(3, 10),
            ),
            chamado("sem_loja", canal="site", prioridade="urgente", aberto_em=em(4, 9)),
            chamado("anterior", loja=loja_a, status="resolvido", aberto_em=em(28, 9, mes=9)),
            chamado("fora", loja=loja_a, aberto_em=em(1, 9, mes=8)),
        ]
    )
    # a2: o cliente escreve primeiro (nao conta); a equipe responde 30 min depois da abertura.
    fab.mensagem(atendimento=ids["a2"], remetente=cliente, enviada_em=em(3, 10, 5))
    fab.mensagem(atendimento=ids["a2"], remetente=atendente_a, enviada_em=em(3, 10, 30))
    # a3: a equipe responde 2 h depois.
    fab.mensagem(atendimento=ids["a3"], remetente=atendente_b, enviada_em=em(3, 12))
    return SimpleNamespace(
        ids=ids, lojas=(loja_a, loja_b), atendente_a=atendente_a, admin=admin, cliente=cliente
    )


def dashboard(sa_conn, quem, **filtro):
    return service.montar_dashboard(
        sa_conn, usuario_atual(quem), inicio=INICIO, fim=FIM, filtro=Filtro(**filtro)
    )


def test_resumo_da_rede_inteira(sa_conn, cenario):
    r = dashboard(sa_conn, cenario.admin)
    assert r["atual"]["total"] == 4  # a1, a2, a3 e o chamado sem loja
    assert r["atual"]["resolvidos"] == 1
    assert r["atual"]["taxa_resolucao"] == 0.25
    assert r["atual"]["resposta_media_horas"] == 1.25  # (0,5 h + 2 h) / 2; o do cliente nao conta
    assert r["anterior"]["total"] == 1
    assert r["anterior"]["taxa_resolucao"] == 1.0
    assert r["anterior"]["resposta_media_horas"] is None


def test_periodo_anterior_tem_a_mesma_duracao(sa_conn, cenario):
    r = dashboard(sa_conn, cenario.admin)
    assert r["periodo_anterior"] == {"inicio": date(2026, 9, 24), "fim": date(2026, 9, 30)}


def test_filtra_por_loja(sa_conn, cenario):
    loja_a, _ = cenario.lojas
    r = dashboard(sa_conn, cenario.atendente_a, id_loja=loja_a)
    assert r["atual"]["total"] == 2
    assert r["atual"]["resposta_media_horas"] == 0.5
    assert [loja["id_loja"] for loja in r["opcoes"]["lojas"]] == [loja_a]
    assert r["escopo"]["pode_escolher_loja"] is False


def test_admin_enxerga_todas_as_lojas_nas_opcoes(sa_conn, cenario):
    r = dashboard(sa_conn, cenario.admin)
    ids = {loja["id_loja"] for loja in r["opcoes"]["lojas"]}
    assert set(cenario.lojas) <= ids
    assert r["escopo"] == {"papel": "admin", "id_loja": None, "pode_escolher_loja": True}


def test_serie_diaria_completa_o_periodo_com_zeros_e_usa_o_fuso_de_sao_paulo(sa_conn, cenario):
    r = dashboard(sa_conn, cenario.admin)
    serie = {linha["data"]: linha["total"] for linha in r["volume_diario"]}
    assert len(serie) == 7
    assert serie[date(2026, 10, 2)] == 1  # a1, aberto as 23:30 em Sao Paulo
    assert serie[date(2026, 10, 3)] == 2
    assert serie[date(2026, 10, 4)] == 1
    assert serie[date(2026, 10, 1)] == 0
    assert sum(serie.values()) == r["atual"]["total"]


def test_chamados_por_categoria_listam_todas_as_categorias(sa_conn, cenario):
    r = dashboard(sa_conn, cenario.admin)
    por_codigo = {linha["codigo"]: linha["total"] for linha in r["por_categoria"]}
    assert len(por_codigo) == 6
    assert por_codigo["entrega"] == 1
    assert por_codigo["pedido"] == 2  # a2 e o chamado sem loja (primeira categoria por padrao)
    assert por_codigo["troca_devolucao"] == 1
    assert sum(por_codigo.values()) == 4


def test_tempo_de_resposta_por_canal(sa_conn, cenario):
    r = dashboard(sa_conn, cenario.admin)
    por_canal = {linha["codigo"]: linha for linha in r["resposta_por_canal"]}
    assert por_canal["whatsapp"]["total"] == 2
    assert por_canal["whatsapp"]["resposta_media_horas"] == 2.0  # so a3 foi respondido
    assert por_canal["email"]["resposta_media_horas"] == 0.5
    assert por_canal["telefone"]["resposta_media_horas"] is None
    assert por_canal["telefone"]["total"] == 0


def test_filtros_de_canal_e_categoria(sa_conn, cenario):
    assert dashboard(sa_conn, cenario.admin, canal="whatsapp")["atual"]["total"] == 2
    assert dashboard(sa_conn, cenario.admin, categoria="entrega")["atual"]["total"] == 1


def test_valor_malicioso_no_filtro_nao_vira_sql(sa_conn, cenario):
    r = dashboard(sa_conn, cenario.admin, canal="x'; DROP TABLE atendimento; --")
    assert r["atual"]["total"] == 0
    assert sa_conn.exec_driver_sql("SELECT count(*) FROM atendimento").scalar() >= 6


def test_fila_so_traz_nao_finalizados_com_contadores(sa_conn, cenario):
    fila = service.montar_fila(sa_conn, Filtro(), limit=20, offset=0)
    ids = {str(item["id_atendimento"]) for item in fila["itens"]}
    esperado = {str(cenario.ids[nome]) for nome in ("a1", "a3", "sem_loja", "fora")}
    assert ids == esperado  # resolvidos ficam de fora
    assert fila["total_aberto"] == 4
    assert fila["sem_resposta"] == 3  # a1, sem_loja e fora estao "aberto"
    assert fila["urgentes"] == 2  # a1 (alta) e sem_loja (urgente)


def test_fila_ordena_por_prioridade_e_depois_pelo_mais_antigo(sa_conn, cenario):
    fila = service.montar_fila(sa_conn, Filtro(), limit=20, offset=0)
    prioridades = [item["prioridade_codigo"] for item in fila["itens"]]
    # "fora" usa a prioridade padrao (baixa), por isso fecha a lista.
    assert prioridades == ["urgente", "alta", "media", "baixa"]


def test_fila_respeita_loja_paginacao_e_assunto(sa_conn, cenario):
    loja_a, _ = cenario.lojas
    fila = service.montar_fila(sa_conn, Filtro(id_loja=loja_a), limit=1, offset=0)
    assert fila["total_aberto"] == 2  # a1 e fora; a2 e o anterior estao resolvidos
    assert len(fila["itens"]) == 1
    assert fila["itens"][0]["assunto"] == "Entrega"  # sem assunto: cai para a categoria
    segunda = service.montar_fila(sa_conn, Filtro(id_loja=loja_a), limit=1, offset=1)
    assert segunda["itens"][0]["id_atendimento"] != fila["itens"][0]["id_atendimento"]


def test_fila_nao_expoe_contato_do_cliente(sa_conn, cenario):
    item = service.montar_fila(sa_conn, Filtro(), limit=1, offset=0)["itens"][0]
    assert {"email", "telefone", "documento"}.isdisjoint(item)
    assert item["cliente_nome"].startswith("Usuario")


def test_atendente_nao_consulta_outra_loja(cenario):
    _, loja_b = cenario.lojas
    usuario = usuario_atual(cenario.atendente_a)
    assert service.resolver_loja(usuario, None) == cenario.lojas[0]
    with pytest.raises(SemPermissao):
        service.resolver_loja(usuario, loja_b)


def test_o_fuso_do_teste_e_realmente_diferente_de_utc():
    assert em(2, 23, 30).astimezone(UTC).date() == date(2026, 10, 3)
