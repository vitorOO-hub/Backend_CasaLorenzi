"""Catalogo, auditoria e integracao do admin contra um Postgres real: so os casos criticos."""

from decimal import Decimal

import pytest

from app.core.erros_auth import SemPermissao
from app.core.papeis import Papel, UsuarioAtual
from app.gestao import auditoria, catalogo, integracoes
from app.gestao.erros import (
    NomeDePecaJaExiste,
    PecaEmUso,
    RegistroJaMapeado,
    SkuInvalido,
    SkuJaExiste,
)
from app.gestao.schemas import NovaPeca, PecaAlterada
from tests.banco.test_chat_repositorio import SemCommit

pytestmark = pytest.mark.banco


class SemCommitNemRollback(SemCommit):
    """Em producao o service desfaz a transacao ao falhar; no teste isso apagaria o cenario."""

    def rollback(self) -> None:
        pass


@pytest.fixture
def sa_conn(sa_conn):
    return SemCommitNemRollback(sa_conn)


def admin_de(usuario):
    return UsuarioAtual(id_auth=usuario.auth, papel=Papel.ADMIN)


def peca(sku="ZZ-0001", nome="Peca de teste", preco="199.90"):
    return NovaPeca(sku=sku, nome=nome, categoria="Camisaria", preco=Decimal(preco))


def acoes_da_auditoria(conn, admin):
    r = auditoria.listar(conn, admin, busca=None, limit=100, offset=0)
    return [(i["acao"], i["detalhe"], i["autor"]) for i in r["itens"]]


def id_da_variacao(conn, sku):
    return conn.exec_driver_sql(
        "SELECT id_variacao FROM variacao_produto WHERE sku = %s", (sku,)
    ).scalar_one()


def test_so_admin_mexe_no_catalogo_na_auditoria_e_na_integracao(sa_conn, fab_sa):
    gerente = fab_sa.usuario("gerente_loja", loja=fab_sa.loja())
    nao_admin = UsuarioAtual(id_auth=gerente.auth, papel=Papel.GERENTE_LOJA, id_loja=gerente.loja)
    for chamada in (
        lambda: catalogo.listar(sa_conn, nao_admin, busca=None, limit=5, offset=0),
        lambda: catalogo.criar(sa_conn, nao_admin, peca()),
        lambda: auditoria.listar(sa_conn, nao_admin, busca=None, limit=5, offset=0),
        lambda: integracoes.montar(sa_conn, nao_admin),
    ):
        with pytest.raises(SemPermissao):
            chamada()


def test_catalogo_criar_listar_editar_e_excluir_com_auditoria(sa_conn, fab_sa):
    admin = admin_de(fab_sa.usuario("diretor"))
    nova = catalogo.criar(sa_conn, admin, peca())
    assert nova["skus"] == ["ZZ-0001"] and nova["preco"] == 199.9 and nova["estoque_rede"] == 0

    # Busca por nome, SKU e categoria (sem diferenciar maiuscula; % nao vira curinga).
    for termo in ("peca de TESTE", "zz-0001", "camisaria"):
        achou = catalogo.listar(sa_conn, admin, busca=termo, limit=10, offset=0)
        assert ["ZZ-0001"] in [i["skus"] for i in achou["itens"]]
    assert catalogo.listar(sa_conn, admin, busca="%", limit=10, offset=0)["total"] == 0

    # O preco vale para todas as variacoes.
    editada = catalogo.alterar(
        sa_conn, admin, nova["id_produto"], PecaAlterada(nome="Peca nova", preco=Decimal("250"))
    )
    assert editada["nome"] == "Peca nova" and editada["preco"] == 250.0

    with pytest.raises(SkuJaExiste):
        catalogo.criar(sa_conn, admin, peca(nome="Outra"))
    with pytest.raises(NomeDePecaJaExiste):
        catalogo.criar(sa_conn, admin, peca(sku="ZZ-0002", nome="peca NOVA"))

    assert catalogo.excluir(sa_conn, admin, nova["id_produto"])["excluido"] is True
    assert catalogo.listar(sa_conn, admin, busca="ZZ-0001", limit=10, offset=0)["total"] == 0

    acoes = {a for a, _, _ in acoes_da_auditoria(sa_conn, admin)}
    assert {
        "Criou produto no catálogo",
        "Editou produto do catálogo",
        "Excluiu produto do catálogo",
    } <= acoes


def test_peca_com_estoque_nao_e_excluida(sa_conn, fab_sa):
    admin = admin_de(fab_sa.usuario("diretor"))
    loja = fab_sa.loja()
    nova = catalogo.criar(sa_conn, admin, peca(sku="ZZ-0003", nome="Com estoque"))
    fab_sa.estoque(loja=loja, variacao=id_da_variacao(sa_conn, "ZZ-0003"), quantidade=4)
    with pytest.raises(PecaEmUso):
        catalogo.excluir(sa_conn, admin, nova["id_produto"])
    item = catalogo.listar(sa_conn, admin, busca="ZZ-0003", limit=5, offset=0)["itens"][0]
    assert item["estoque_rede"] == 4


def test_auditoria_busca_e_registra_quem_fez(sa_conn, fab_sa):
    quem = fab_sa.usuario("diretor")
    admin = admin_de(quem)
    auditoria.registrar(sa_conn, admin, "Aprovou ajuste manual", "CL-0001 · 3 un.")
    auditoria.registrar(sa_conn, admin, "Definiu estoque mínimo", "2 peça(s)")
    nome = sa_conn.exec_driver_sql(
        "SELECT nome FROM usuario WHERE id_usuario = %s", (quem.id,)
    ).scalar_one()
    todos = auditoria.listar(sa_conn, admin, busca=None, limit=10, offset=0)
    assert todos["itens"][0]["autor"] == nome
    so_ajuste = auditoria.listar(sa_conn, admin, busca="CL-0001", limit=10, offset=0)
    assert [i["acao"] for i in so_ajuste["itens"]] == ["Aprovou ajuste manual"]
    assert auditoria.listar(sa_conn, admin, busca="%", limit=10, offset=0)["total"] == 0


def test_integracao_lotes_registros_e_mapeamento(sa_conn, fab_sa):
    admin = admin_de(fab_sa.usuario("diretor"))
    catalogo.criar(sa_conn, admin, peca(sku="ZZ-0009", nome="Para mapear"))
    id_variacao = id_da_variacao(sa_conn, "ZZ-0009")
    lote = sa_conn.exec_driver_sql(
        "INSERT INTO importacao_lote (codigo) VALUES ('IMP-T-1') RETURNING id_lote"
    ).scalar_one()
    outro = sa_conn.exec_driver_sql(
        "INSERT INTO importacao_lote (codigo, com_erro) VALUES ('IMP-T-2', true) RETURNING id_lote"
    ).scalar_one()
    ids = {}
    for chave, id_lote, codigo in (
        ("a", lote, "VLT-1"),
        ("b", lote, "VLT-2"),
        ("c", outro, "VLT-1"),
    ):
        ids[chave] = sa_conn.exec_driver_sql(
            "INSERT INTO importacao_registro (id_lote, descricao_externa, codigo_externo) "
            "VALUES (%s, 'CAMISA X', %s) RETURNING id_registro",
            (id_lote, codigo),
        ).scalar_one()

    antes = integracoes.montar(sa_conn, admin)
    lotes = {x["codigo"]: x for x in antes["lotes"]}
    assert (lotes["IMP-T-1"]["registros"], lotes["IMP-T-1"]["pendentes"]) == (2, 2)
    assert lotes["IMP-T-1"]["situacao"] == "pendente_mapeamento"
    assert lotes["IMP-T-2"]["situacao"] == "com_erro"
    assert "ZZ-0009" in {s["sku"] for s in antes["skus"]}

    with pytest.raises(SkuInvalido):  # id que nao e de nenhuma variacao
        integracoes.mapear(sa_conn, admin, ids["a"], ids["b"])
    feito = integracoes.mapear(sa_conn, admin, ids["a"], id_variacao)
    assert feito["sku_mapeado"] == "ZZ-0009"
    with pytest.raises(RegistroJaMapeado):
        integracoes.mapear(sa_conn, admin, ids["a"], id_variacao)

    depois = integracoes.montar(sa_conn, admin)
    por_id = {str(r["id_registro"]): r for r in depois["registros"]}
    # O mesmo codigo do ERP, no outro lote, ganha o mesmo SKU; o outro codigo continua pendente.
    assert por_id[str(ids["c"])]["sku_mapeado"] == "ZZ-0009"
    assert por_id[str(ids["b"])]["sku_mapeado"] is None
    lotes = {x["codigo"]: x for x in depois["lotes"]}
    assert lotes["IMP-T-1"]["pendentes"] == 1
    auditados = [(a, d) for a, d, _ in acoes_da_auditoria(sa_conn, admin)]
    assert ("Mapeou registro de importação", "VLT-1 → ZZ-0009") in auditados
