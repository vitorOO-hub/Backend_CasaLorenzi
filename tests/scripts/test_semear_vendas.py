"""A simulacao de vendas do script de exemplo: coerencia interna, sem banco."""

import importlib.util
import random
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

CAMINHO = Path(__file__).resolve().parents[2] / "scripts" / "semear_vendas.py"
_spec = importlib.util.spec_from_file_location("semear_vendas", CAMINHO)
semear_vendas = importlib.util.module_from_spec(_spec)
sys.modules["semear_vendas"] = semear_vendas
_spec.loader.exec_module(semear_vendas)

AGORA = datetime(2026, 10, 7, 15, 0, tzinfo=timezone(timedelta(hours=-3)))
SINAL = {
    "entrada": 1,
    "ajuste_positivo": 1,
    "cancelamento_venda": 1,
    "transferencia_entrada": 1,
    "saida": -1,
    "ajuste_negativo": -1,
    "venda": -1,
    "transferencia_saida": -1,
}


@pytest.fixture(scope="module")
def mundo():
    lojas = {codigo: uuid4() for codigo, *_ in semear_vendas.LOJAS}
    equipes = {
        codigo: semear_vendas.Equipe(uuid4(), uuid4(), (uuid4(), uuid4())) for codigo in lojas
    }
    variacoes = []
    for peca in (semear_vendas.LINHO, *semear_vendas.CATALOGO):
        id_produto = uuid4()
        for _cor, _tamanho, sku in semear_vendas.grade(peca):
            variacoes.append(
                semear_vendas.Variacao(uuid4(), id_produto, sku, peca.preco, peca.popularidade)
            )
    clientes = [uuid4() for _ in range(20)]
    plano = semear_vendas.simular(
        lojas=lojas,
        variacoes=variacoes,
        clientes=clientes,
        equipes=equipes,
        agora=AGORA,
        rng=random.Random(semear_vendas.SEMENTE),
    )
    return plano, lojas, variacoes, equipes


def test_a_semente_gera_sempre_o_mesmo_historico(mundo):
    plano, lojas, variacoes, equipes = mundo
    segunda = semear_vendas.simular(
        lojas=lojas,
        variacoes=variacoes,
        clientes=[p[3] for p in plano.pedidos[:1]] or [uuid4()],
        equipes=equipes,
        agora=AGORA,
        rng=random.Random(semear_vendas.SEMENTE),
    )
    assert [p[1] for p in segunda.pedidos] == [p[1] for p in plano.pedidos]


def test_ha_volume_realista_de_pedidos(mundo):
    plano, *_ = mundo
    assert 1200 < len(plano.pedidos) < 4000
    assert len(plano.itens) >= len(plano.pedidos)
    datas = [p[8] for p in plano.pedidos]
    assert max(datas) <= AGORA - timedelta(minutes=5)
    assert min(datas) >= AGORA - timedelta(days=semear_vendas.DIAS_DE_HISTORICO + 1)


def test_numeros_de_pedido_sao_unicos_e_marcados(mundo):
    plano, *_ = mundo
    numeros = [p[1] for p in plano.pedidos]
    assert len(set(numeros)) == len(numeros)
    assert all(n.startswith(semear_vendas.PREFIXO_PEDIDO) for n in numeros)


def test_total_do_pedido_e_itens_mais_frete(mundo):
    plano, *_ = mundo
    por_pedido = defaultdict(float)
    for id_pedido, _v, quantidade, preco, _q in plano.itens:
        por_pedido[id_pedido] += quantidade * preco
    for pedido in plano.pedidos:
        id_pedido, total, frete = pedido[0], pedido[6], pedido[11]
        assert total == pytest.approx(por_pedido[id_pedido] + frete, abs=0.011)


def test_item_nao_se_repete_dentro_do_pedido(mundo):
    plano, *_ = mundo
    chaves = [(i[0], i[1]) for i in plano.itens]
    assert len(set(chaves)) == len(chaves)


def test_frete_so_no_online_e_nunca_em_compra_grande(mundo):
    plano, *_ = mundo
    for pedido in plano.pedidos:
        canal, frete, total = pedido[10], pedido[11], pedido[6]
        if canal == "loja":
            assert frete == 0
        assert frete == 0 or total - frete < 800
    canais = {p[10] for p in plano.pedidos}
    assert canais == {"loja", "online"}


def test_observacao_do_online_segue_o_formato_do_portal(mundo):
    plano, *_ = mundo
    online = [p for p in plano.pedidos if p[10] == "online"]
    assert online and all(p[7].startswith("Checkout pelo portal. Entrega: ") for p in online)
    assert all(f"Frete: R$ {p[11]:.2f}." in p[7] for p in online)


def test_status_e_pagamento_combinam(mundo):
    plano, *_ = mundo
    status = {p[0]: p[5] for p in plano.pedidos}
    assert set(status.values()) >= {"entregue", "cancelado", "pago", "separado"}
    pagamentos = {p[0]: p for p in plano.pagamentos}
    assert len(pagamentos) == len(plano.pagamentos)  # um por pedido
    for id_pedido, estado in status.items():
        if estado == "criado":
            assert id_pedido not in pagamentos
            continue
        pagamento = pagamentos[id_pedido]
        esperado = {"aguardando_pagamento": "pendente", "cancelado": "estornado"}.get(
            estado, "aprovado"
        )
        assert pagamento[3] == esperado
        assert (pagamento[6] is None) == (esperado == "pendente")
    totais = {p[0]: p[6] for p in plano.pedidos}
    assert all(p[4] == pytest.approx(totais[p[0]]) for p in plano.pagamentos)


def test_pedido_online_antigo_nao_fica_parado(mundo):
    plano, *_ = mundo
    antigos = [p for p in plano.pedidos if p[8] < AGORA - timedelta(days=14)]
    assert {p[5] for p in antigos} <= {"entregue", "cancelado"}


def test_saldo_de_cada_peca_encadeia_e_nunca_fica_negativo(mundo):
    plano, *_ = mundo
    ultimo = {}
    relogio = {}
    for (
        loja,
        variacao,
        _pedido,
        _usuario,
        tipo,
        quantidade,
        anterior,
        posterior,
        _m,
        quando,
    ) in plano.movimentos:
        chave = (loja, variacao)
        assert quantidade > 0 and anterior >= 0 and posterior >= 0
        assert posterior == anterior + SINAL[tipo] * quantidade
        assert anterior == ultimo.get(chave, 0)  # cada movimento parte de onde o anterior parou
        assert quando >= relogio.get(chave, quando)  # e o relogio nao anda para tras
        ultimo[chave], relogio[chave] = posterior, quando
    for chave, (quantidade, minimo) in plano.estoque.items():
        assert quantidade == ultimo[chave] and minimo > 0


def test_venda_e_cancelamento_apontam_para_um_pedido_e_o_resto_nao(mundo):
    plano, *_ = mundo
    pedidos = {p[0]: p[5] for p in plano.pedidos}
    for movimento in plano.movimentos:
        id_pedido, tipo = movimento[2], movimento[4]
        if tipo in ("venda", "cancelamento_venda"):
            assert id_pedido in pedidos
        else:
            assert id_pedido is None
    vendas = {m[2] for m in plano.movimentos if m[4] == "venda"}
    for id_pedido, status in pedidos.items():
        assert (id_pedido in vendas) == (status not in ("criado", "aguardando_pagamento"))
    cancelados = {m[2] for m in plano.movimentos if m[4] == "cancelamento_venda"}
    assert cancelados == {i for i, s in pedidos.items() if s == "cancelado"}


def test_quantidade_vendida_confere_com_os_itens(mundo):
    plano, *_ = mundo
    itens = defaultdict(int)
    for id_pedido, variacao, quantidade, *_ in plano.itens:
        itens[(id_pedido, variacao)] += quantidade
    vendido = defaultdict(int)
    for m in plano.movimentos:
        if m[4] == "venda":
            vendido[(m[2], m[1])] += m[5]
    pedidos_baixados = {m[2] for m in plano.movimentos if m[4] == "venda"}
    assert vendido == {k: v for k, v in itens.items() if k[0] in pedidos_baixados}


def test_ha_pecas_esgotadas_ou_no_minimo_para_a_tela_de_reposicao(mundo):
    plano, *_ = mundo
    esgotadas = [k for k, (q, _m) in plano.estoque.items() if q == 0]
    no_minimo = [k for k, (q, m) in plano.estoque.items() if 0 < q <= m]
    assert esgotadas and no_minimo


def test_cada_loja_vende_e_a_maior_vende_mais(mundo):
    plano, lojas, *_ = mundo
    por_loja = defaultdict(int)
    for pedido in plano.pedidos:
        por_loja[pedido[2]] += 1
    assert set(por_loja) == set(lojas.values())
    assert (
        por_loja[lojas["LOJA-CENTRO"]]
        > por_loja[lojas["LOJA-BARRA"]]
        > por_loja[lojas["LOJA-SAVASSI"]]
    )


def test_pendencias_para_o_gerente(mundo):
    plano, lojas, *_ = mundo
    pendentes = [a for a in plano.ajustes if a[6] == "pendente"]
    assert len(pendentes) == 6 and {a[0] for a in pendentes} == set(lojas.values())
    for a in plano.ajustes:  # decisao so existe em quem foi decidido
        assert (a[3] is None) == (a[6] == "pendente") and (a[8] is None) == (a[6] == "pendente")
        assert a[4] != 0
    solicitadas = [t for t in plano.transferencias if t[1] == "solicitada"]
    aceitas = [t for t in plano.transferencias if t[1] == "recebida"]
    assert len(solicitadas) == 4 and len(aceitas) == 2
    assert any(t[0] == "reposicao_rede" and t[2] is None for t in solicitadas)
    assert all(t[2] != t[3] for t in plano.transferencias)
    assert all(t[6] is not None and t[10] is not None for t in aceitas)


def test_skus_seguem_o_padrao_que_o_front_reconhece(mundo):
    _, _, variacoes, _ = mundo
    prefixos = (
        "CL-CAM-LIN",
        "CL-CAM-OXF",
        "CL-CAL-ALF",
        "CL-BLA",
        "CL-VES-MID",
        "CL-VES-SLI",
        "CL-TRI",
        "CL-SUE",
        "CL-TRE",
        "CL-JAQ",
        "CL-SAI",
        "CL-BOL",
        "CL-CIN",
        "CL-MOC",
        "CL-BOT",
    )
    skus = [v.sku for v in variacoes]
    assert len(set(skus)) == len(skus)
    assert {p for p in prefixos if any(s.startswith(p + "-") for s in skus)} == set(prefixos)
