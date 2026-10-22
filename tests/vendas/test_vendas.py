"""Vendas em loja sem banco real (o SQL foi ensaiado contra o banco com rollback)."""

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.db import get_executar
from app.core.erros_auth import SemPermissao
from app.core.papeis import Papel, UsuarioAtual
from app.main import criar_app
from app.vendas import repositorio, service
from app.vendas.erros import (
    ClienteNaoEncontrado,
    EstoqueInsuficiente,
    LojaDaVendaInvalida,
    PecaIndisponivel,
    VendaNaoEncontrada,
    VendaNaoRegistrada,
)
from tests.auth_util import SUPABASE_URL, ParDeChaves, provedor_para
from tests.conftest import DATABASE_URL_TESTE, ErroBancoFalso

LOJA = uuid4()
ECOMMERCE = uuid4()
VENDEDOR = UsuarioAtual(id_auth=uuid4(), papel=Papel.VENDEDOR, id_loja=LOJA)
ID_VENDEDOR = uuid4()
ID_CLIENTE = uuid4()
PECA_A, PECA_B = UUID(int=1), UUID(int=2)
CPF = "52998224725"
DETALHE_DE_VERDADE = service._detalhe


class ConexaoFalsa:
    def __init__(self) -> None:
        self.eventos: list[str] = []

    def commit(self) -> None:
        self.eventos.append("commit")

    def rollback(self) -> None:
        self.eventos.append("rollback")


@pytest.fixture
def banco(monkeypatch):
    """Estoque e cliente de mentira; registra o que a venda gravou."""
    estado = {
        "estoque": {
            PECA_A: (5, "SKU-A", Decimal("100.00")),
            PECA_B: (1, "SKU-B", Decimal("49.90")),
        },
        "cliente": {"id_cliente": ID_CLIENTE, "nome": "ana", "cpf": CPF},
        "loja_ativa": True,
        "loja_de_venda": {},  # loja do vendedor -> loja que recebe a venda (padrao: ela mesma)
        "chave": None,
        "chaves_travadas": [],
        "baixas": [],
        "pedido": None,
        "pagamento": None,
        "detalhes": [],
    }

    def loja_ativa(_c, _l):
        return "loja" if estado["loja_ativa"] else None

    def travar(_c, _loja, id_variacao):
        if id_variacao not in estado["estoque"]:
            return None
        qtd, sku, preco = estado["estoque"][id_variacao]
        return {"quantidade": qtd, "sku": sku, "preco_venda": preco}

    def inserir_pedido(_c, valores):
        estado["pedido"] = valores
        return uuid4()

    def detalhe(_c, id_loja, id_pedido):
        estado["detalhes"].append((id_loja, id_pedido))
        return {"id_pedido": id_pedido}

    def travar_chave(_c, chave):
        estado["chaves_travadas"].append(chave)

    monkeypatch.setattr(service, "id_usuario_ativo", lambda _c, _a: ID_VENDEDOR)
    monkeypatch.setattr(repositorio, "nome_da_loja", loja_ativa)
    monkeypatch.setattr(
        repositorio, "loja_de_venda", lambda _c, loja: estado["loja_de_venda"].get(loja, loja)
    )
    monkeypatch.setattr(repositorio, "travar_chave", travar_chave)
    monkeypatch.setattr(repositorio, "cliente_por_cpf", lambda _c, _cpf: estado["cliente"])
    monkeypatch.setattr(repositorio, "venda_da_chave", lambda _c, _v, _k: estado["chave"])
    monkeypatch.setattr(repositorio, "id_de_apoio", lambda _c, tabela, codigo: f"{tabela}:{codigo}")
    monkeypatch.setattr(repositorio, "travar_peca", travar)
    monkeypatch.setattr(repositorio, "inserir_pedido", inserir_pedido)
    monkeypatch.setattr(repositorio, "baixar_item", lambda _c, **kw: estado["baixas"].append(kw))
    monkeypatch.setattr(
        repositorio, "inserir_pagamento", lambda _c, **kw: estado.update(pagamento=kw)
    )
    monkeypatch.setattr(service, "_detalhe", detalhe)
    return estado


def venda(*itens, metodo="pix", observacao=None):
    corpo = {
        "cpf": CPF,
        "metodo_pagamento": metodo,
        "itens": [{"id_variacao": i, "quantidade": q} for i, q in itens],
    }
    if observacao is not None:
        corpo["observacao"] = observacao
    return corpo


# ------------------------------------------------------------------ servico


def test_mascara_o_cpf():
    assert repositorio.mascarar_cpf("52998224725") == "***.***.***-25"
    assert repositorio.mascarar_cpf(None) == "***.***.***-**"


def test_venda_baixa_o_estoque_soma_o_total_e_grava_uma_vez(banco):
    conexao = ConexaoFalsa()
    service.lancar_venda(conexao, VENDEDOR, venda((PECA_A, 2), (PECA_B, 1)))
    assert conexao.eventos == ["commit"]
    # numero, loja, cliente, vendedor, status, total, observacao
    assert banco["pedido"][1:5] == (LOJA, ID_CLIENTE, ID_VENDEDOR, "status_pedido:entregue")
    assert banco["pedido"][5] == Decimal("249.90")
    assert banco["pedido"][6] == "Venda lancada em loja pelo vendedor."
    baixas = {b["id_variacao"]: b for b in banco["baixas"]}
    assert baixas[PECA_A]["anterior"] == 5 and baixas[PECA_A]["quantidade"] == 2
    assert baixas[PECA_B]["anterior"] == 1 and baixas[PECA_B]["quantidade"] == 1
    assert banco["pagamento"]["valor"] == Decimal("249.90")
    assert banco["pagamento"]["id_metodo"] == "metodo_pagamento:pix"
    assert banco["baixas"][0]["id_tipo_venda"] == "tipo_movimentacao_estoque:venda"


def test_troca_entra_como_venda_com_a_observacao(banco):
    # REGRAS_OPERACAO: troca na loja = venda nova com obs "troca" (baixa a peca nova do estoque).
    service.lancar_venda(ConexaoFalsa(), VENDEDOR, venda((PECA_A, 1), observacao="troca"))
    assert banco["pedido"][6] == "Venda lancada em loja pelo vendedor. Obs: troca"
    assert len(banco["baixas"]) == 1


def test_mesma_peca_repetida_vira_uma_linha(banco):
    service.lancar_venda(ConexaoFalsa(), VENDEDOR, venda((PECA_A, 2), (PECA_A, 3)))
    assert len(banco["baixas"]) == 1
    assert banco["baixas"][0]["quantidade"] == 5


def test_saldo_insuficiente_desfaz_tudo(banco):
    conexao = ConexaoFalsa()
    with pytest.raises(EstoqueInsuficiente) as erro:
        service.lancar_venda(conexao, VENDEDOR, venda((PECA_B, 2)))
    assert "SKU-B" in erro.value.detalhe and "1" in erro.value.detalhe
    assert conexao.eventos == ["rollback"]
    assert banco["pedido"] is None and banco["baixas"] == []


def test_uma_peca_boa_e_uma_sem_saldo_nao_baixa_nenhuma(banco):
    conexao = ConexaoFalsa()
    with pytest.raises(EstoqueInsuficiente):
        service.lancar_venda(conexao, VENDEDOR, venda((PECA_A, 1), (PECA_B, 9)))
    assert banco["baixas"] == [] and conexao.eventos == ["rollback"]


def test_peca_fora_do_estoque_da_loja(banco):
    with pytest.raises(PecaIndisponivel):
        service.lancar_venda(ConexaoFalsa(), VENDEDOR, venda((uuid4(), 1)))


def test_cpf_sem_cadastro(banco):
    banco["cliente"] = None
    conexao = ConexaoFalsa()
    with pytest.raises(ClienteNaoEncontrado):
        service.lancar_venda(conexao, VENDEDOR, venda((PECA_A, 1)))
    assert conexao.eventos == ["rollback"]


def test_loja_inativa_ou_sem_loja_nao_vende(banco):
    banco["loja_ativa"] = False
    with pytest.raises(LojaDaVendaInvalida):
        service.lancar_venda(ConexaoFalsa(), VENDEDOR, venda((PECA_A, 1)))
    sem_loja = UsuarioAtual(id_auth=uuid4(), papel=Papel.VENDEDOR, id_loja=None)
    with pytest.raises(SemPermissao):
        service.lancar_venda(ConexaoFalsa(), sem_loja, venda((PECA_A, 1)))


def test_mesma_chave_trava_e_devolve_a_venda_anterior_sem_gravar(banco):
    anterior = uuid4()
    banco["chave"] = anterior
    conexao = ConexaoFalsa()
    r = service.lancar_venda(conexao, VENDEDOR, venda((PECA_A, 1)), chave_idempotencia="k1")
    assert r == {"id_pedido": anterior}
    assert banco["chaves_travadas"] == ["venda-loja-k1"]
    assert banco["pedido"] is None and "commit" not in conexao.eventos


def test_recusa_do_banco_vira_409_e_desfaz(banco, monkeypatch, erro_integridade):
    def falha(*_a, **_k):
        raise erro_integridade("23514")  # ex.: o saldo ficaria negativo

    monkeypatch.setattr(repositorio, "baixar_item", falha)
    conexao = ConexaoFalsa()
    with pytest.raises(VendaNaoRegistrada):
        service.lancar_venda(conexao, VENDEDOR, venda((PECA_A, 1)))
    assert conexao.eventos == ["rollback"]


def test_venda_do_canal_online_vai_para_a_loja_de_venda(banco):
    """Vendedor de canal que virou o e-commerce: pedido, estoque e detalhe na mesma loja."""
    banco["loja_de_venda"][LOJA] = ECOMMERCE
    service.lancar_venda(ConexaoFalsa(), VENDEDOR, venda((PECA_A, 1)))
    assert banco["pedido"][1] == ECOMMERCE
    assert banco["baixas"][0]["id_loja"] == ECOMMERCE
    assert banco["detalhes"][-1][0] == ECOMMERCE


def test_cpf_dos_resultados_sai_mascarado():
    assert service._cliente_publico({"cpf": CPF, "nome": "ana"})["cpf"] == "***.***.***-25"
    assert service._venda_publica({"cliente_cpf": CPF})["cliente_cpf"] == "***.***.***-25"


def test_vendas_listadas_e_abertas_so_da_loja_do_vendedor(banco, monkeypatch):
    vistos = []

    def listar(_c, id_loja, busca, *, limit, offset):
        vistos.append(("lista", id_loja))
        return 0, []

    def por_id(_c, id_loja, id_pedido):
        vistos.append(("detalhe", id_loja))
        return None  # venda de outra loja: o SQL nao a devolve

    monkeypatch.setattr(service, "_detalhe", DETALHE_DE_VERDADE)
    monkeypatch.setattr(repositorio, "listar_vendas", listar)
    monkeypatch.setattr(repositorio, "venda_por_id", por_id)
    service.listar_vendas(ConexaoFalsa(), VENDEDOR, "x", limit=5, offset=0)
    with pytest.raises(VendaNaoEncontrada):
        service.obter_venda(ConexaoFalsa(), VENDEDOR, uuid4())
    assert vistos == [("lista", LOJA), ("detalhe", LOJA)]
    sem_loja = UsuarioAtual(id_auth=uuid4(), papel=Papel.VENDEDOR, id_loja=None)
    with pytest.raises(SemPermissao):
        service.listar_vendas(ConexaoFalsa(), sem_loja, None, limit=5, offset=0)


def test_lista_de_clientes_usa_a_loja_do_token(banco, monkeypatch):
    vistos = []

    def listar(_c, id_loja, id_loja_venda, busca, *, limit, offset):
        vistos.append((id_loja, id_loja_venda, busca, limit, offset))
        return 0, []

    monkeypatch.setattr(repositorio, "listar_clientes", listar)
    service.listar_clientes(ConexaoFalsa(), VENDEDOR, "ana", limit=5, offset=10)
    assert vistos == [(LOJA, LOJA, "ana", 5, 10)]
    sem_loja = UsuarioAtual(id_auth=uuid4(), papel=Papel.VENDEDOR, id_loja=None)
    with pytest.raises(SemPermissao):
        service.listar_clientes(ConexaoFalsa(), sem_loja, None, limit=5, offset=0)


# ----------------------------------------------------------------------- HTTP


@pytest.fixture
def http(banco):
    par = ParDeChaves()
    app = criar_app(
        Settings(_env_file=None, database_url=DATABASE_URL_TESTE, supabase_url=SUPABASE_URL)
    )
    app.state.provedor_chaves = provedor_para(par)
    conexao = ConexaoFalsa()
    app.dependency_overrides[get_executar] = lambda: lambda operacao: operacao(conexao)
    cliente = TestClient(app, raise_server_exceptions=False)
    token = par.emitir(papel="vendedor", loja_id=str(LOJA))
    cliente.headers.update({"Authorization": f"Bearer {token}"})
    return cliente


ITEM = {"id_variacao": str(PECA_A), "quantidade": 1}


@pytest.mark.parametrize(
    "corpo",
    [
        {"cpf": "123", "metodo_pagamento": "pix", "itens": [ITEM]},
        {"cpf": CPF, "metodo_pagamento": "boleto", "itens": [ITEM]},
        {"cpf": CPF, "metodo_pagamento": "pix", "itens": []},
        {"cpf": CPF, "metodo_pagamento": "pix", "itens": [{**ITEM, "quantidade": 0}]},
        {"cpf": CPF, "metodo_pagamento": "pix", "itens": [{**ITEM, "quantidade": 100}]},
        {"cpf": CPF, "metodo_pagamento": "pix", "itens": [{**ITEM, "id_variacao": "x"}]},
        {"cpf": CPF, "metodo_pagamento": "pix", "itens": [ITEM], "observacao": "x" * 301},
        # nada de loja, vendedor ou preco vindo do corpo
        {"cpf": CPF, "metodo_pagamento": "pix", "id_loja": str(uuid4()), "itens": [ITEM]},
        {"cpf": CPF, "metodo_pagamento": "pix", "itens": [{**ITEM, "preco": "1.00"}]},
    ],
)
def test_corpo_invalido_e_422_e_nao_vende(http, banco, corpo):
    assert http.post("/api/v1/painel/vendas", json=corpo).status_code == 422
    assert banco["pedido"] is None


def test_venda_pela_api_aceita_cpf_com_pontuacao_e_observacao(http, banco):
    corpo = {"cpf": "529.982.247-25", "metodo_pagamento": "pix", "itens": [ITEM]}
    corpo["observacao"] = "  troca  "
    r = http.post("/api/v1/painel/vendas", json=corpo, headers={"Idempotency-Key": "abc"})
    assert r.status_code not in (403, 422)
    assert banco["pedido"][6].endswith("Obs: troca")
    assert banco["chaves_travadas"] == ["venda-loja-abc"]


def test_cpf_inexistente_na_busca_e_404(http, banco):
    banco["cliente"] = None
    r = http.post("/api/v1/painel/vendas/clientes/buscar", json={"cpf": CPF})
    assert r.status_code == 404
    assert "CPF" in r.json()["detail"]


def test_recusa_do_banco_pela_api_e_409_em_portugues(http, banco, monkeypatch):
    def falha(*_a, **_k):
        raise IntegrityError("SQL", {}, ErroBancoFalso("23505"))

    monkeypatch.setattr(repositorio, "inserir_pedido", falha)
    corpo = {"cpf": CPF, "metodo_pagamento": "pix", "itens": [ITEM]}
    r = http.post("/api/v1/painel/vendas", json=corpo)
    assert r.status_code == 409
    assert "tente de novo" in r.json()["detail"]


def test_lista_pela_api_ignora_loja_enviada_na_consulta(http, banco, monkeypatch):
    vistos = []
    monkeypatch.setattr(
        repositorio,
        "listar_vendas",
        lambda _c, id_loja, busca, *, limit, offset: vistos.append(id_loja) or (0, []),
    )
    monkeypatch.setattr(
        repositorio,
        "listar_clientes",
        lambda _c, id_loja, _venda, busca, *, limit, offset: vistos.append(id_loja) or (0, []),
    )
    falsa = str(uuid4())
    assert http.get("/api/v1/painel/vendas", params={"id_loja": falsa}).status_code == 200
    assert http.get("/api/v1/painel/vendas/clientes", params={"id_loja": falsa}).status_code == 200
    assert vistos == [LOJA, LOJA]
