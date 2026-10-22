"""Fila de vendas pendentes do Vulto contra um Postgres real: detalhe sem dados pessoais,
importar como pedido (na loja de origem, sem pontos novos) e descartar com o porque."""

import json
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.erros_auth import SemPermissao
from app.core.papeis import Papel, UsuarioAtual
from app.gestao import vendas_pendentes as fila
from app.gestao.erros import ClienteDaVendaInvalido, VendaJaResolvida

pytestmark = pytest.mark.banco

CPF = "52998224725"


def admin(fab_sa):
    pessoa = fab_sa.usuario("diretor")
    return UsuarioAtual(id_auth=pessoa.auth, papel=Papel.ADMIN, id_loja=None)


@pytest.fixture
def cena(fab_sa):
    c = fab_sa.conn
    for codigo, nome in (
        ("LOJA-VULTO-APP", "vulto app"),
        ("E-COMMERCE-CASA-LORENZI", "e-commerce"),
    ):
        c.execute(
            "INSERT INTO loja (codigo, nome) VALUES (%s, %s) ON CONFLICT (codigo) DO NOTHING",
            (codigo, nome),
        )
    cliente = fab_sa.usuario("cliente")
    c.execute("UPDATE usuario SET documento = %s WHERE id_usuario = %s", (CPF, cliente.id))
    variacao, outra = fab_sa.variacao(), fab_sa.variacao()
    sku = c.execute(
        "SELECT sku FROM variacao_produto WHERE id_variacao = %s", (variacao,)
    ).fetchone()[0]
    lote = c.execute(
        "INSERT INTO importacao_lote (codigo, origem) VALUES (%s, 'Vulto vendas') "
        "RETURNING id_lote",
        (f"LOTE-{uuid4()}",),
    ).fetchone()[0]
    venda_id = str(uuid4().int)[:9]
    dados = {
        "venda": {
            "id": int(venda_id),
            "loja_id": 6,  # app da Vulto
            "status_padronizado": "concluida",
            "data_hora_padronizada": "2025-03-10T15:00:00-03:00",
            "total_decimal": "200.00",
            "frete_decimal": "0.00",
            "desconto_decimal": "0.00",
            "cpf_padronizado": CPF,
            "cliente_ref": "fulana@exemplo.com",
            "vendedor_padronizado": "app",
        },
        "itens": [
            {
                "sku_padronizado": sku,
                "descricao": "camisa",
                "qtd": 1,
                "preco_unitario_decimal": "180.00",
            },
            {
                "sku_padronizado": "NAO-EXISTE",
                "descricao": "calca",
                "qtd": 1,
                "preco_unitario_decimal": "20.00",
            },
        ],
        "compra": None,
    }
    id_venda = c.execute(
        """
        INSERT INTO venda_importacao_pendente (id_lote, origem, venda_id_origem, status_origem,
            motivos, quantidade_itens, dados_origem)
        VALUES (%s, 'vulto', %s, 'concluida', %s, 2, %s) RETURNING id_venda_pendente
        """,
        (lote, venda_id, ["sku:variacao_nao_encontrada"], json.dumps(dados)),
    ).fetchone()[0]
    return SimpleNamespace(
        c=c, cliente=cliente, variacao=variacao, outra=outra, id=id_venda, venda_id=venda_id
    )


def resolucao(cena, **extra):
    return SimpleNamespace(
        id_cliente=cena.cliente.id,
        valor_total=Decimal("200.00"),
        valor_frete=Decimal("0"),
        itens=[
            SimpleNamespace(id_variacao=cena.variacao, quantidade=1, preco_unitario=Decimal("180")),
            SimpleNamespace(id_variacao=cena.outra, quantidade=1, preco_unitario=Decimal("20")),
        ],
        observacao=None,
        **extra,
    )


def test_detalhe_sugere_cliente_e_peca_sem_expor_dados_pessoais(sa_conn, fab_sa, cena):
    d = fila.detalhe(sa_conn, admin(fab_sa), cena.id)
    assert d["sugestao_cliente"]["id_cliente"] == cena.cliente.id
    assert d["cpf_final"] == CPF[-4:]
    assert (d["loja"], d["canal"], d["status_destino"]) == ("vulto app", "online", "pago")
    assert d["itens"][0]["variacao_sugerida"]["id_variacao"] == cena.variacao
    assert d["itens"][1]["variacao_sugerida"] is None
    texto = str(d)
    assert CPF not in texto and "fulana" not in texto


def test_importar_grava_pedido_na_loja_de_origem_sem_pontos_novos(sa_conn, fab_sa, cena):
    d = fila.importar(sa_conn, admin(fab_sa), cena.id, resolucao(cena))
    assert d["estado"] == "importada"
    pedido = cena.c.execute(
        "SELECT l.codigo, p.valor_total, p.canal_venda, "
        "(SELECT count(*) FROM item_pedido i WHERE i.id_pedido = p.id_pedido) "
        "FROM pedido p JOIN loja l USING (id_loja) WHERE p.numero_pedido = %s",
        (f"VULTO-{cena.venda_id}",),
    ).fetchone()
    # Venda antiga fica no app da Vulto (nao vai para o e-commerce unificado).
    assert pedido == ("LOJA-VULTO-APP", Decimal("200.00"), "online", 2)
    assert (
        cena.c.execute(
            "SELECT count(*) FROM movimento_pontos WHERE id_usuario = %s", (cena.cliente.id,)
        ).fetchone()[0]
        == 0
    )
    assert (
        cena.c.execute(
            "SELECT count(*) FROM venda_importacao_origem WHERE chave_origem = %s", (cena.venda_id,)
        ).fetchone()[0]
        == 1
    )
    with pytest.raises(VendaJaResolvida):
        fila.importar(sa_conn, admin(fab_sa), cena.id, resolucao(cena))


def test_importar_recusa_peca_repetida(sa_conn, fab_sa, cena):
    from app.gestao.erros import PecaRepetidaNaVenda

    r = resolucao(cena)
    r.itens[1].id_variacao = cena.variacao
    with pytest.raises(PecaRepetidaNaVenda):
        fila.importar(sa_conn, admin(fab_sa), cena.id, r)


def test_importar_exige_cliente(sa_conn, fab_sa, cena):
    atendente = fab_sa.usuario("atendente", loja=fab_sa.loja())
    r = resolucao(cena)
    r.id_cliente = atendente.id
    with pytest.raises(ClienteDaVendaInvalido):
        fila.importar(sa_conn, admin(fab_sa), cena.id, r)


def test_descartar_guarda_o_porque_e_sai_da_fila(sa_conn, fab_sa, cena):
    quem = admin(fab_sa)
    d = fila.descartar(sa_conn, quem, cena.id, "venda de teste da loja")
    assert (d["estado"], d["observacao_resolucao"]) == ("descartada", "venda de teste da loja")
    pendentes = fila.listar(sa_conn, quem, limit=100, grupo="sku")
    assert cena.venda_id not in [i["venda_id_origem"] for i in pendentes["itens"]]
    descartadas = fila.listar(sa_conn, quem, limit=100, estado="descartada")
    assert cena.venda_id in [i["venda_id_origem"] for i in descartadas["itens"]]


def test_filtro_por_grupo_e_resumo(sa_conn, fab_sa, cena):
    quem = admin(fab_sa)
    assert cena.venda_id in [
        i["venda_id_origem"] for i in fila.listar(sa_conn, quem, limit=100, grupo="sku")["itens"]
    ]
    assert cena.venda_id not in [
        i["venda_id_origem"]
        for i in fila.listar(sa_conn, quem, limit=100, grupo="cliente")["itens"]
    ]
    assert {"grupo": "sku", "vendas": 1} in fila.resumo_por_grupo(sa_conn, quem, "pendente")


def test_so_admin(sa_conn, fab_sa, cena):
    gerente = UsuarioAtual(id_auth=uuid4(), papel=Papel.GERENTE_LOJA, id_loja=fab_sa.loja())
    for chamada in (
        lambda: fila.detalhe(sa_conn, gerente, cena.id),
        lambda: fila.descartar(sa_conn, gerente, cena.id, "xxx"),
        lambda: fila.importar(sa_conn, gerente, cena.id, resolucao(cena)),
    ):
        with pytest.raises(SemPermissao):
            chamada()
