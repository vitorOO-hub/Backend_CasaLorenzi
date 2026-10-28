"""Assistente do visitante: so catalogo publico, login pedido no chat, limites por IP."""

from datetime import date

import pytest

from app.assistente.cliente import ferramentas as modulo_ferramentas
from app.assistente.cliente import visitante
from app.assistente.cliente.erros import LimiteDiarioDoAssistente
from app.assistente.cliente.provedor import ChamadaFeita, ErroProvedor, RespostaProvedor
from app.core.config import Settings
from tests.conftest import DATABASE_URL_TESTE


class ConexaoFalsa:
    def rollback(self):
        pass


class ProvedorFalso:
    def __init__(self, resposta=None, erro=None, chamar=()):
        self.resposta, self.erro, self.chamar = resposta, erro, chamar
        self.pedidos: list[dict] = []

    def responder(self, **kwargs):
        self.pedidos.append(kwargs)
        if self.erro:
            raise self.erro
        chamadas = [ChamadaFeita(n, a, kwargs["executar"](n, a)) for n, a in self.chamar]
        resposta = self.resposta or RespostaProvedor(texto="ok")
        resposta.chamadas = chamadas + resposta.chamadas
        return resposta


def _settings(**extras):
    base = {"groq_api_key": "chave-groq", "gemini_api_key": "chave-gemini"}
    return Settings(_env_file=None, database_url=DATABASE_URL_TESTE, **{**base, **extras})


def _responder(texto, provedor=None, historico=(), configuracoes=None):
    fabricados = []

    def fabrica(destino, cfg):
        fabricados.append(destino)
        return provedor or ProvedorFalso()

    resposta = visitante.responder(
        ConexaoFalsa(),
        texto,
        list(historico),
        configuracoes=configuracoes or _settings(),
        fabrica=fabrica,
    )
    return resposta, fabricados


@pytest.fixture(autouse=True)
def _sem_service_do_cliente(monkeypatch):
    """Nenhum service que dependa do cliente pode ser chamado pelo visitante."""

    def proibido(*a, **k):
        raise AssertionError("visitante chegou a um service do cliente")

    for nome in (
        "listar_lojas",
        "obter_vulto_mais",
        "listar_pedidos",
        "adicionar_item_carrinho",
        "criar_chamado",
    ):
        monkeypatch.setattr(modulo_ferramentas.cliente, nome, proibido)


def test_visitante_busca_peca_e_ve_lojas_sem_login(monkeypatch):
    monkeypatch.setattr(
        modulo_ferramentas.repositorio,
        "buscar_produtos",
        lambda conexao, termos, limite: [{"nome": "Camisa Linho", "variacoes": []}],
    )
    monkeypatch.setattr(
        modulo_ferramentas.cliente_repositorio,
        "listar_lojas",
        lambda conexao: [{"nome": "Vulto Batel", "horario_funcionamento": None}],
    )
    provedor = ProvedorFalso(
        RespostaProvedor(texto="Temos a Camisa Linho."),
        chamar=[("buscar_produto", {"descricao": "camisa linho"}), ("info_loja", {})],
    )
    resposta, _ = _responder("tem camisa de linho?", provedor)
    assert resposta == {
        "resposta": "Temos a Camisa Linho.",
        "sem_resposta": False,
        "precisa_login": False,
    }
    busca, lojas = [c.resultado for c in provedor.resposta.chamadas]
    assert busca["pecas"][0]["nome"] == "Camisa Linho"
    assert lojas["lojas"][0]["nome"] == "Vulto Batel"


@pytest.mark.parametrize(
    ("nome", "argumentos"),
    [
        ("consultar_pontos", {}),
        ("consultar_pedidos", {}),
        ("montar_carrinho", {"sku": "VLT-1-AZ-M"}),
        ("transferir_para_atendente", {"motivo": "Troca", "resumo": "Quer trocar a peca M por G."}),
    ],
)
def test_pedido_da_conta_pede_login_no_chat(nome, argumentos):
    provedor = ProvedorFalso(RespostaProvedor(texto="qualquer coisa"), chamar=[(nome, argumentos)])
    resposta, _ = _responder("quero isso", provedor)
    assert resposta["precisa_login"] is True
    assert resposta["resposta"] == visitante.TEXTO_PRECISA_LOGIN
    (chamada,) = provedor.resposta.chamadas
    assert chamada.resultado["erro"] == "precisa_login"


def test_sem_resposta_segura_oferece_login_para_falar_com_a_equipe():
    # Pergunta de dado do sistema respondida sem consulta: o texto do modelo nao passa.
    provedor = ProvedorFalso(RespostaProvedor(texto="A loja abre as 9h."))
    resposta, _ = _responder("qual o horario da loja batel?", provedor)
    assert resposta["resposta"] == visitante.TEXTO_SEM_RESPOSTA
    assert resposta["precisa_login"] is True and resposta["sem_resposta"] is True


def test_erro_do_provedor_oferece_login_e_chave_ausente_so_avisa():
    resposta, _ = _responder("oi", ProvedorFalso(erro=ErroProvedor("groq", "tempo esgotado")))
    assert resposta["resposta"] == visitante.TEXTO_SEM_RESPOSTA and resposta["precisa_login"]
    resposta, _ = _responder("oi", ProvedorFalso(erro=ErroProvedor("groq", "chave ausente")))
    assert resposta["resposta"] == visitante.TEXTO_INDISPONIVEL and not resposta["precisa_login"]


def test_sem_modelo_configurado_so_avisa_sem_chamar_provedor():
    resposta, fabricados = _responder("oi", configuracoes=_settings(groq_api_key=None))
    assert fabricados == []
    assert resposta["resposta"] == visitante.TEXTO_INDISPONIVEL


def test_pergunta_incompleta_pede_esclarecimento_sem_modelo():
    resposta, fabricados = _responder("tem essa peca na loja?")
    assert fabricados == []
    assert resposta["resposta"] == visitante.TEXTO_ESCLARECER


def test_historico_do_navegador_e_limitado_e_vai_antes_da_pergunta():
    historico = [
        {"autor": "usuario" if i % 2 == 0 else "assistente", "texto": f"m{i}"} for i in range(30)
    ]
    provedor = ProvedorFalso()
    _responder("oi", provedor, historico)
    enviado = provedor.pedidos[0]["historico"]
    assert len(enviado) == visitante.LIMITE_HISTORICO + 1
    assert enviado[0]["texto"] == "m20" and enviado[-1] == {"papel": "usuario", "texto": "oi"}
    assert "NAO entrou na conta" in provedor.pedidos[0]["sistema"]


def test_teto_diario_por_ip_vira_429_e_zera_no_dia_seguinte():
    contador = visitante.ContadorDiario(limite=2)
    hoje, amanha = date(2026, 10, 28), date(2026, 10, 29)
    contador.registrar("1.1.1.1", hoje)
    contador.registrar("1.1.1.1", hoje)
    with pytest.raises(LimiteDiarioDoAssistente):
        contador.registrar("1.1.1.1", hoje)
    contador.registrar("2.2.2.2", hoje)  # outro IP tem a propria conta
    contador.registrar("1.1.1.1", amanha)
