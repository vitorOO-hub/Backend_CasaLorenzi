"""Testes das rotas administrativas sem banco real."""

from decimal import Decimal

import pytest

from app.admin.erros import RegistroAdminNaoEncontrado
from app.admin.schemas import ProdutoCriacao
from app.core.db import get_executar

ID_UUID = "6f1c3a52-6a4e-4c8e-9a39-0f1f2b6f2f10"
LINHA = {"id_registro": ID_UUID, "nome": "Registro de teste"}

ROTAS_ADMIN_ESPERADAS = {
    ("GET", "/admin/lojas"),
    ("POST", "/admin/lojas"),
    ("GET", "/admin/lojas/{id_loja}"),
    ("PATCH", "/admin/lojas/{id_loja}"),
    ("DELETE", "/admin/lojas/{id_loja}"),
    ("GET", "/admin/usuarios"),
    ("POST", "/admin/usuarios"),
    ("GET", "/admin/usuarios/{id_usuario}"),
    ("PATCH", "/admin/usuarios/{id_usuario}"),
    ("DELETE", "/admin/usuarios/{id_usuario}"),
    ("GET", "/admin/produtos"),
    ("POST", "/admin/produtos"),
    ("GET", "/admin/produtos/{id_produto}"),
    ("PATCH", "/admin/produtos/{id_produto}"),
    ("DELETE", "/admin/produtos/{id_produto}"),
    ("GET", "/admin/variacoes"),
    ("POST", "/admin/variacoes"),
    ("GET", "/admin/variacoes/{id_variacao}"),
    ("PATCH", "/admin/variacoes/{id_variacao}"),
    ("DELETE", "/admin/variacoes/{id_variacao}"),
    ("GET", "/admin/{nome_opcao}"),
    ("GET", "/admin/{nome_opcao}/{id_registro}"),
    ("DELETE", "/admin/{nome_opcao}/{id_registro}"),
}


def usar_executor(app, executor):
    app.dependency_overrides[get_executar] = lambda: executor


def devolve(resultado):
    return lambda _operacao: resultado


def levanta(erro):
    def executor(_operacao):
        raise erro

    return executor


def test_rotas_administrativas_estao_registradas(cliente):
    caminhos = cliente.get("/openapi.json").json()["paths"]
    registradas = {
        (metodo.upper(), caminho) for caminho, itens in caminhos.items() for metodo in itens
    }
    assert ROTAS_ADMIN_ESPERADAS.issubset(registradas)


def test_criar_loja_responde_201(app, cliente):
    usar_executor(app, devolve({"id_loja": ID_UUID, "nome": "Casa Lorenzi Centro"}))
    resposta = cliente.post(
        "/admin/lojas",
        json={"codigo": "CENTRO", "nome": "Casa Lorenzi Centro", "uf": "SP"},
    )
    assert resposta.status_code == 201
    assert resposta.json()["id_loja"] == ID_UUID


def test_usuario_rejeita_campo_de_permissao_desconhecido(cliente):
    resposta = cliente.post(
        "/admin/usuarios",
        json={
            "id_tipo_usuario": ID_UUID,
            "nome": "Ana",
            "email": "ana@example.com",
            "papel": "diretor",
        },
    )
    assert resposta.status_code == 422


def test_produto_usa_decimal_no_schema():
    produto = ProdutoCriacao(nome="Camisa", preco_base="149.90")
    assert isinstance(produto.preco_base, Decimal)
    assert produto.preco_base == Decimal("149.90")


def test_criar_produto_duplicado_responde_409(app, cliente, erro_integridade):
    usar_executor(app, levanta(erro_integridade("23505")))
    resposta = cliente.post(
        "/admin/produtos",
        json={"nome": "Camisa", "preco_base": "149.90"},
    )
    assert resposta.status_code == 409
    assert resposta.json() == {"detail": "Produto ja existe"}


def test_obter_produto_inexistente_responde_404(app, cliente):
    usar_executor(app, levanta(RegistroAdminNaoEncontrado("Produto")))
    resposta = cliente.get(f"/admin/produtos/{ID_UUID}")
    assert resposta.status_code == 404
    assert resposta.json() == {"detail": "Produto nao encontrado"}


@pytest.mark.parametrize(
    ("caminho", "corpo"),
    [
        ("/admin/tipos-usuario", {"codigo": "cliente", "nome": "Cliente"}),
        ("/admin/status-pedido", {"codigo": "pago", "nome": "Pago"}),
        ("/admin/metodos-pagamento", {"codigo": "pix", "nome": "PIX"}),
        ("/admin/status-pagamento", {"codigo": "aprovado", "nome": "Aprovado"}),
        (
            "/admin/tipos-movimentacao-estoque",
            {"codigo": "entrada", "nome": "Entrada", "sinal": 1},
        ),
    ],
)
def test_criar_opcoes_do_banco_responde_201(app, cliente, caminho, corpo):
    usar_executor(app, devolve(LINHA))
    resposta = cliente.post(caminho, json=corpo)
    assert resposta.status_code == 201
    assert resposta.json() == LINHA
