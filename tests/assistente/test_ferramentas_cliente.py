"""Ferramentas do assistente: argumentos validados, cliente do token, falha sem invencao."""

from uuid import uuid4

import pytest

from app.assistente.cliente import ferramentas as modulo
from app.assistente.cliente.ferramentas import DECLARACOES, Ferramentas
from app.core.papeis import UsuarioAtual
from app.core.protecoes import LimitadorDeRequisicoes

CLIENTE = UsuarioAtual(id_auth=uuid4())


class ConexaoFalsa:
    rollbacks = 0

    def rollback(self):
        self.rollbacks += 1


@pytest.fixture
def ferramentas():
    return Ferramentas(ConexaoFalsa(), CLIENTE)


def test_toda_declaracao_tem_executor_e_esquema_fechado():
    for declaracao in DECLARACOES:
        assert hasattr(Ferramentas, f"_{declaracao.nome}")
        assert declaracao.parametros["type"] == "object"
        assert declaracao.parametros["additionalProperties"] is False
        # Nenhuma ferramenta aceita dizer quem e o cliente.
        assert not {"id_cliente", "id_usuario", "cpf", "email"} & set(
            declaracao.parametros["properties"]
        )


def test_ferramenta_desconhecida(ferramentas):
    assert ferramentas.executar("apagar_pedido", {}) == {"erro": "ferramenta_desconhecida"}
    assert ferramentas.executar("__init__", {}) == {"erro": "ferramenta_desconhecida"}


@pytest.mark.parametrize(
    ("nome", "argumentos"),
    [
        ("buscar_produto", {}),
        ("buscar_produto", {"descricao": "x"}),
        ("consultar_estoque", {"sku": "abc; DROP TABLE"}),
        ("consultar_pontos", {"id_cliente": str(uuid4())}),
        ("consultar_pedidos", {"id_usuario": "outro"}),
        ("montar_carrinho", {"sku": "VLT-1", "quantidade": 0}),
        ("montar_carrinho", {"sku": "VLT-1", "quantidade": 500}),
        ("transferir_para_atendente", {"motivo": "oi", "resumo": "curto"}),
    ],
)
def test_argumento_invalido_ou_extra_e_recusado_sem_chamar_service(
    ferramentas, monkeypatch, nome, argumentos
):
    def nao_chamar(*a, **k):
        raise AssertionError("service nao deveria ser chamado")

    for funcao in (
        "listar_estoque_catalogo",
        "obter_vulto_mais",
        "listar_pedidos",
        "adicionar_item_carrinho",
        "criar_chamado",
    ):
        monkeypatch.setattr(modulo.cliente, funcao, nao_chamar)
    monkeypatch.setattr(modulo.repositorio, "buscar_produtos", nao_chamar)
    assert ferramentas.executar(nome, argumentos) == {"erro": "argumentos_invalidos"}


def test_falha_na_consulta_vira_erro_explicito_e_libera_a_transacao(ferramentas, monkeypatch):
    def quebra(*a, **k):
        raise RuntimeError("banco fora")

    monkeypatch.setattr(modulo.cliente, "obter_vulto_mais", quebra)
    assert ferramentas.executar("consultar_pontos", {}) == {"erro": "nao_foi_possivel_consultar"}
    assert ferramentas.conexao.rollbacks == 1


def test_consultas_do_cliente_usam_o_usuario_do_token(ferramentas, monkeypatch):
    vistos = []

    def pontos(conexao, usuario):
        vistos.append(usuario)
        return {
            "saldo": 340,
            "categoria": "prata",
            "proxima_categoria": "ouro",
            "faltam_para_proxima": 2660,
            "pontos_a_vencer": 0,
            "proximos_vencimentos": [],
            "beneficios": [{"titulo": "Frete gratis"}],
            "regras": {"reais_a_cada_100_pontos": 5},
        }

    def pedidos(conexao, usuario, *, limit, offset):
        vistos.append(usuario)
        assert (limit, offset) == (modulo.LIMITE_PEDIDOS, 0)
        return [
            {
                "numero_pedido": "PD-1",
                "status": "Pago",
                "valor_total": 99,
                "loja": "Savassi",
                "itens": [{"produto": "Camisa", "cor": "azul", "tamanho": "M", "quantidade": 1}],
            }
        ]

    monkeypatch.setattr(modulo.cliente, "obter_vulto_mais", pontos)
    monkeypatch.setattr(modulo.cliente, "listar_pedidos", pedidos)
    resultado = ferramentas.executar("consultar_pontos", {})
    assert resultado["saldo"] == 340 and resultado["beneficios"] == ["Frete gratis"]
    assert ferramentas.executar("consultar_pedidos", {})["pedidos"][0]["pecas"] == [
        "Camisa (azul, M) x1"
    ]
    assert vistos == [CLIENTE, CLIENTE]


def test_estoque_filtra_pelo_sku_e_pela_loja_sem_acento(ferramentas, monkeypatch):
    monkeypatch.setattr(
        modulo.cliente,
        "listar_estoque_catalogo",
        lambda conexao: [
            {"sku": "VLT-1-AZ-M", "loja": "Vulto Savassi", "quantidade": 2},
            {"sku": "VLT-1-AZ-M", "loja": "Casa Lorenzi Ibirapuera", "quantidade": 3},
            {"sku": "VLT-2", "loja": "Vulto Savassi", "quantidade": 9},
        ],
    )
    tudo = ferramentas.executar("consultar_estoque", {"sku": "vlt-1-az-m"})
    assert tudo["total"] == 5 and len(tudo["por_loja"]) == 2
    loja = ferramentas.executar("consultar_estoque", {"sku": "VLT-1-AZ-M", "loja": "ibirapuéra"})
    assert loja["por_loja"] == [{"loja": "Casa Lorenzi Ibirapuera", "quantidade": 3}]
    assert ferramentas.executar("consultar_estoque", {"sku": "VLT-999"}) == {
        "sku": "VLT-999",
        "encontrado": False,
    }


def test_info_loja_mantem_horario_nulo(ferramentas, monkeypatch):
    monkeypatch.setattr(
        modulo.cliente,
        "listar_lojas",
        lambda conexao, usuario: [{"nome": "Vulto Savassi", "horario_funcionamento": None}],
    )
    (loja,) = ferramentas.executar("info_loja", {"loja": "savassi"})["lojas"]
    assert loja["horario_funcionamento"] is None


def test_montar_carrinho_com_sku_inexistente_nao_mexe_na_sacola(ferramentas, monkeypatch):
    monkeypatch.setattr(modulo.repositorio, "variacao_ativa_pelo_sku", lambda conexao, sku: None)
    assert ferramentas.executar("montar_carrinho", {"sku": "VLT-404"}) == {
        "adicionado": False,
        "motivo": "sku_nao_encontrado",
    }
    assert ferramentas.carrinho_alterado is False


def test_montar_carrinho_adiciona_para_o_cliente_do_token(ferramentas, monkeypatch):
    id_variacao = uuid4()
    chamadas = []
    monkeypatch.setattr(
        modulo.repositorio, "variacao_ativa_pelo_sku", lambda conexao, sku: id_variacao
    )
    monkeypatch.setattr(
        modulo.cliente,
        "adicionar_item_carrinho",
        lambda conexao, usuario, dados: chamadas.append((usuario, dados)),
    )
    assert (
        ferramentas.executar("montar_carrinho", {"sku": "vlt-1", "quantidade": 2})["adicionado"]
        is True
    )
    assert chamadas == [(CLIENTE, {"id_variacao": id_variacao, "quantidade": 2})]
    assert ferramentas.carrinho_alterado is True


def test_mensagem_do_assistente_conta_como_escrita_sensivel_no_limite_por_ip():
    limitador = LimitadorDeRequisicoes(app=None)
    assert (
        limitador._tipo("POST", f"/api/v1/assistente/cliente/conversas/{uuid4()}/mensagens")
        == "sensivel"
    )
    assert limitador._tipo("POST", "/api/v1/assistente/cliente/conversas") == "escrita"
    assert limitador._tipo("GET", f"/api/v1/assistente/cliente/conversas/{uuid4()}") == "leitura"
