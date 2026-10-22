"""Lista de clientes do painel com o Vulto+: loja de cadastro, saldo, categoria e os filtros.
Contra um Postgres real."""

import pytest

from app.chamados import service as chamados
from app.clientes import service
from app.core.papeis import Papel, UsuarioAtual

pytestmark = pytest.mark.banco


def admin(usuario) -> UsuarioAtual:
    return UsuarioAtual(id_auth=usuario.auth, papel=Papel.ADMIN, id_loja=None)


def lista(conexao, usuario, **filtros):
    token = admin(usuario)
    escopo = chamados.montar_escopo(conexao, token, None)
    base = dict(busca=None, secao="todos", limit=100, offset=0)
    return service.listar(conexao, token, escopo, **{**base, **filtros})


@pytest.fixture
def cena(fab_sa):
    c = fab_sa.conn
    loja_v, loja_c = fab_sa.loja(), fab_sa.loja()
    ouro, bronze, fora = (fab_sa.usuario("cliente") for _ in range(3))
    for cliente, loja in ((ouro, loja_v), (bronze, loja_v), (fora, loja_c)):
        c.execute("UPDATE usuario SET id_loja = %s WHERE id_usuario = %s", (loja, cliente.id))
    for cliente, pontos in ((ouro, 6000), (bronze, 300)):
        c.execute(
            "INSERT INTO movimento_pontos (id_usuario, tipo, pontos, ocorrido_em, descricao) "
            "VALUES (%s, 'credito', %s, now(), 'teste')",
            (cliente.id, pontos),
        )
    return {
        "admin": fab_sa.usuario("diretor"),
        "ouro": ouro,
        "bronze": bronze,
        "fora": fora,
        "loja_v": loja_v,
        "loja_c": loja_c,
    }


def por_id(r):
    return {str(i["id_cliente"]): i for i in r["itens"]}


def test_lista_traz_loja_de_cadastro_saldo_e_categoria(sa_conn, cena):
    itens = por_id(lista(sa_conn, cena["admin"]))
    ouro, fora = itens[str(cena["ouro"].id)], itens[str(cena["fora"].id)]
    assert (ouro["saldo_pontos"], ouro["categoria_vulto_mais"]) == (6000, "ouro")
    assert ouro["id_loja_cadastro"] == cena["loja_v"] and ouro["loja_cadastro"]
    assert (fora["saldo_pontos"], fora["categoria_vulto_mais"]) == (None, None)


@pytest.mark.parametrize(
    ("categoria", "esperados"),
    [("ouro", {"ouro"}), ("bronze", {"bronze"}), ("sem_pontos", {"fora"})],
)
def test_filtro_por_categoria(sa_conn, cena, categoria, esperados):
    ids = set(por_id(lista(sa_conn, cena["admin"], categoria=categoria)))
    meus = {nome: str(cena[nome].id) for nome in ("ouro", "bronze", "fora")}
    assert {nome for nome, i in meus.items() if i in ids} == esperados


def test_filtro_por_loja_de_cadastro(sa_conn, cena):
    ids = set(por_id(lista(sa_conn, cena["admin"], id_loja_cadastro=cena["loja_c"])))
    assert ids == {str(cena["fora"].id)}


def test_opcoes_trazem_as_lojas_com_cliente_e_as_categorias(sa_conn, cena):
    o = service.opcoes(sa_conn)
    lojas = {x["id_loja"] for x in o["lojas_cadastro"]}
    assert {cena["loja_v"], cena["loja_c"]} <= lojas
    assert [c["codigo"] for c in o["categorias"]] == ["ouro", "prata", "bronze", "sem_pontos"]


def test_filtro_por_marca_do_cadastro(sa_conn, cena):
    # A marca vem do codigo da loja de cadastro: loja Vulto comeca com LOJA-VULTO.
    sa_conn.exec_driver_sql(
        "UPDATE loja SET codigo = 'LOJA-VULTO-TESTE-' || id_loja WHERE id_loja = %(l)s",
        {"l": cena["loja_v"]},
    )
    vulto = set(por_id(lista(sa_conn, cena["admin"], marca="vulto")))
    casa = set(por_id(lista(sa_conn, cena["admin"], marca="casa_lorenzi")))
    assert {str(cena["ouro"].id), str(cena["bronze"].id)} <= vulto
    assert str(cena["fora"].id) in casa and str(cena["ouro"].id) not in casa
