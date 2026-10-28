"""Fluxo do assistente: repositorio em memoria e provedor falso (sem rede, sem banco)."""

from uuid import UUID, uuid4

import pytest

from app.assistente import ferramentas as modulo_ferramentas
from app.assistente import service
from app.assistente.erros import (
    ConversaComAtendente,
    ConversaNaoEncontrada,
    LimiteDiarioDoAssistente,
)
from app.assistente.ferramentas import Ferramentas
from app.assistente.provedor import ChamadaFeita, ErroProvedor, RespostaProvedor
from app.core.config import Settings
from app.core.erros_auth import SemPermissao
from app.core.papeis import Papel, UsuarioAtual
from tests.conftest import DATABASE_URL_TESTE

CLIENTE = UsuarioAtual(id_auth=uuid4())
ID_USUARIO = uuid4()


class ConexaoFalsa:
    def __init__(self):
        self.commits = self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class RepositorioFalso:
    def __init__(self):
        self.conversas: dict[UUID, dict] = {}
        self.mensagens: list[dict] = []
        self.hoje = 0

    def criar_conversa(self, conexao, id_usuario, tipo):
        conversa = {
            "id_conversa": uuid4(),
            "id_usuario": id_usuario,
            "tipo": tipo,
            "status": "ativa",
            "id_atendimento": None,
            "criada_em": "2026-10-27T10:00:00Z",
        }
        self.conversas[conversa["id_conversa"]] = conversa
        return {k: v for k, v in conversa.items() if k != "id_usuario"}

    def obter_conversa(self, conexao, id_conversa, id_usuario, *, travar=False):
        conversa = self.conversas.get(id_conversa)
        return dict(conversa) if conversa and conversa["id_usuario"] == id_usuario else None

    def mensagens_visiveis(self, conexao, id_conversa, limite):
        visiveis = [
            m
            for m in self.mensagens
            if m["id_conversa"] == id_conversa and m["autor"] != "ferramenta"
        ]
        return visiveis[-limite:]

    def gravar_mensagem(self, conexao, id_conversa, autor, texto_="", **extras):
        self.mensagens.append(
            {"id_conversa": id_conversa, "autor": autor, "texto": texto_, **extras}
        )

    def mensagens_do_usuario_hoje(self, conexao, id_usuario):
        return self.hoje

    def passar_para_atendente(self, conexao, id_conversa, id_atendimento):
        self.conversas[id_conversa].update(status="com_atendente", id_atendimento=id_atendimento)


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


@pytest.fixture
def repo(monkeypatch):
    falso = RepositorioFalso()
    for nome in (
        "criar_conversa",
        "obter_conversa",
        "mensagens_visiveis",
        "gravar_mensagem",
        "mensagens_do_usuario_hoje",
        "passar_para_atendente",
    ):
        monkeypatch.setattr(service.repositorio, nome, getattr(falso, nome))
    monkeypatch.setattr(
        service.cliente_repositorio, "id_cliente_ativo", lambda conexao, auth: ID_USUARIO
    )
    return falso


def _settings(**extras):
    base = {"groq_api_key": "chave-groq", "gemini_api_key": "chave-gemini"}
    return Settings(_env_file=None, database_url=DATABASE_URL_TESTE, **{**base, **extras})


def _enviar(repo, texto, provedor=None, configuracoes=None, usuario=CLIENTE, conversa=None):
    conexao = ConexaoFalsa()
    if conversa is None:
        conversa = service.iniciar_conversa(conexao, usuario)["id_conversa"]
    fabricados = []

    def fabrica(destino, cfg):
        fabricados.append(destino)
        return provedor or ProvedorFalso()

    resposta = service.enviar_mensagem(
        conexao,
        usuario,
        conversa,
        texto,
        configuracoes=configuracoes or _settings(),
        fabrica=fabrica,
    )
    return resposta, fabricados, conexao


def _assistente(repo):
    return [m for m in repo.mensagens if m["autor"] == "assistente"][-1]


# ------------------------------------------------------------------ sucesso


def test_pergunta_simples_vai_ao_modelo_rapido_e_grava_tudo(repo):
    provedor = ProvedorFalso(
        RespostaProvedor(texto="  Ola! Posso ajudar.  ", tokens_entrada=12, tokens_saida=4)
    )
    resposta, fabricados, conexao = _enviar(repo, "oi, tudo bem?", provedor)
    assert resposta["resposta"] == "Ola! Posso ajudar."
    assert resposta["status"] == "ativa" and not resposta["sem_resposta"]
    assert [(d.provedor, d.modelo) for d in fabricados] == [("groq", "openai/gpt-oss-20b")]
    pedido = provedor.pedidos[0]
    assert pedido["max_tokens"] == service.MAX_TOKENS_SAIDA
    assert pedido["max_rodadas"] == service.MAX_RODADAS_FERRAMENTA
    assert pedido["historico"][-1] == {"papel": "usuario", "texto": "oi, tudo bem?"}
    gravada = _assistente(repo)
    assert gravada["modelo"] == "groq:openai/gpt-oss-20b"
    assert (gravada["tokens_entrada"], gravada["tokens_saida"]) == (12, 4)
    assert [m["autor"] for m in repo.mensagens] == ["usuario", "assistente"]
    # Abrir a conversa; a pergunta, confirmada antes de chamar o modelo; e a resposta depois.
    assert conexao.commits == 3


def test_pergunta_sensivel_vai_ao_modelo_preciso_e_grava_a_ferramenta(repo, monkeypatch):
    monkeypatch.setattr(
        Ferramentas, "_consultar_pontos", lambda self, args: {"saldo": 340, "categoria": "prata"}
    )
    provedor = ProvedorFalso(
        RespostaProvedor(texto="Voce tem 340 pontos."), chamar=[("consultar_pontos", {})]
    )
    resposta, fabricados, _ = _enviar(repo, "quantos pontos eu tenho?", provedor)
    assert fabricados[0].provedor == "gemini"
    assert resposta["resposta"] == "Voce tem 340 pontos." and not resposta["sem_resposta"]
    (registro,) = [m for m in repo.mensagens if m["autor"] == "ferramenta"]
    assert registro["ferramenta"] == "consultar_pontos"
    assert registro["dados"]["resultado"] == {"saldo": 340, "categoria": "prata"}


def test_historico_enviado_ao_modelo_e_limitado(repo):
    conexao = ConexaoFalsa()
    conversa = service.iniciar_conversa(conexao, CLIENTE)["id_conversa"]
    for i in range(30):
        repo.gravar_mensagem(conexao, conversa, "usuario" if i % 2 == 0 else "assistente", f"m{i}")
    provedor = ProvedorFalso()
    _enviar(repo, "oi", provedor, conversa=conversa)
    historico = provedor.pedidos[0]["historico"]
    assert len(historico) == service.LIMITE_HISTORICO + 1
    assert historico[0]["texto"] == "m20"


def test_resposta_do_modelo_e_cortada_no_limite(repo):
    provedor = ProvedorFalso(RespostaProvedor(texto="a" * 10_000))
    resposta, _, _ = _enviar(repo, "oi", provedor)
    assert len(resposta["resposta"]) == service.LIMITE_CARACTERES_RESPOSTA


def test_resposta_que_dependia_de_dado_sem_consulta_fica_marcada(repo):
    provedor = ProvedorFalso(RespostaProvedor(texto="Voce tem uns 300 pontos."))
    resposta, _, _ = _enviar(repo, "quantos pontos eu tenho?", provedor)
    assert resposta["sem_resposta"] is True
    assert _assistente(repo)["sem_resposta"] is True


def test_resposta_vazia_ou_rodadas_esgotadas_viram_texto_controlado(repo):
    for resposta_modelo in (
        RespostaProvedor(texto="  "),
        RespostaProvedor(texto="x", concluida=False),
    ):
        resposta, _, _ = _enviar(repo, "oi", ProvedorFalso(resposta_modelo))
        assert resposta["resposta"] == service.TEXTO_SEM_RESPOSTA
        assert resposta["sem_resposta"] is True


# ------------------------------------------------------------------ estados do roteador


def test_pergunta_incompleta_pede_esclarecimento_sem_chamar_modelo(repo):
    resposta, fabricados, _ = _enviar(repo, "tem essa peca na loja?")
    assert fabricados == []
    assert resposta["resposta"] == service.TEXTO_ESCLARECER
    assert _assistente(repo)["modelo"] is None
    assert _assistente(repo)["dados"]["estado"] == "esclarecer"


@pytest.mark.parametrize(
    ("configuracoes", "estado"),
    [
        (_settings(assistente_modelo_rapido=None), "modelo_nao_configurado"),
        (
            _settings().model_copy(update={"assistente_modelo_rapido": "openai:gpt"}),
            "configuracao_invalida",
        ),
        (_settings(groq_api_key=None), "provedor_sem_chave"),
        (_settings(groq_api_key="   "), "provedor_sem_chave"),
    ],
)
def test_configuracao_quebrada_responde_controlado_sem_fallback(repo, configuracoes, estado):
    # A chave do Gemini existe, mas a rota rapida nao pode cair nele em silencio.
    resposta, fabricados, _ = _enviar(repo, "oi, tudo bem?", configuracoes=configuracoes)
    assert fabricados == []
    assert resposta["resposta"] == service.TEXTO_INDISPONIVEL
    assert resposta["sem_resposta"] is True
    assert _assistente(repo)["dados"]["estado"] == estado


def test_erro_do_provedor_vira_resposta_controlada_sem_trocar_de_modelo(repo):
    provedor = ProvedorFalso(erro=ErroProvedor("groq", "resposta de erro do provedor", 503))
    resposta, fabricados, _ = _enviar(repo, "oi, tudo bem?", provedor)
    assert len(fabricados) == 1
    assert resposta["resposta"] == service.TEXTO_FALHA_PROVEDOR
    assert resposta["sem_resposta"] is True
    gravada = _assistente(repo)
    assert gravada["dados"]["erro"] == "resposta de erro do provedor"
    assert gravada["dados"]["status_http"] == 503
    # A pergunta continua registrada.
    assert [m["autor"] for m in repo.mensagens] == ["usuario", "assistente"]


def test_chave_ausente_na_fabrica_tambem_e_controlada(repo):
    conexao = ConexaoFalsa()
    conversa = service.iniciar_conversa(conexao, CLIENTE)["id_conversa"]

    def fabrica(destino, cfg):
        raise ErroProvedor(destino.provedor, "chave ausente")

    resposta = service.enviar_mensagem(
        conexao, CLIENTE, conversa, "oi", configuracoes=_settings(), fabrica=fabrica
    )
    assert resposta["resposta"] == service.TEXTO_FALHA_PROVEDOR


# ------------------------------------------------------------------ permissoes e escopo


@pytest.mark.parametrize("papel", list(Papel))
def test_equipe_nao_usa_o_assistente_do_cliente(repo, papel):
    equipe = UsuarioAtual(
        id_auth=uuid4(), papel=papel, id_loja=None if papel is Papel.ADMIN else uuid4()
    )
    with pytest.raises(SemPermissao):
        service.iniciar_conversa(ConexaoFalsa(), equipe)
    with pytest.raises(SemPermissao):
        service.enviar_mensagem(ConexaoFalsa(), equipe, uuid4(), "oi", configuracoes=_settings())


def test_conversa_de_outro_cliente_nao_existe_para_mim(repo):
    conversa = service.iniciar_conversa(ConexaoFalsa(), CLIENTE)["id_conversa"]
    repo.conversas[conversa]["id_usuario"] = uuid4()
    with pytest.raises(ConversaNaoEncontrada):
        service.obter_conversa(ConexaoFalsa(), CLIENTE, conversa)
    with pytest.raises(ConversaNaoEncontrada):
        _enviar(repo, "oi", conversa=conversa)
    assert repo.mensagens == []


def test_conversa_interna_nao_abre_pelo_assistente_do_cliente(repo):
    conversa = service.iniciar_conversa(ConexaoFalsa(), CLIENTE)["id_conversa"]
    repo.conversas[conversa]["tipo"] = "interno"
    with pytest.raises(ConversaNaoEncontrada):
        _enviar(repo, "oi", conversa=conversa)


def test_conversa_com_atendente_nao_volta_para_o_modelo(repo):
    conversa = service.iniciar_conversa(ConexaoFalsa(), CLIENTE)["id_conversa"]
    repo.conversas[conversa]["status"] = "com_atendente"
    with pytest.raises(ConversaComAtendente):
        _enviar(repo, "oi", conversa=conversa)


def test_limite_diario_por_cliente(repo):
    repo.hoje = service.LIMITE_DIARIO_POR_CLIENTE
    with pytest.raises(LimiteDiarioDoAssistente):
        _enviar(repo, "oi")
    assert repo.mensagens == []


def test_transferencia_passa_a_conversa_para_o_atendente(repo, monkeypatch):
    id_atendimento = uuid4()
    recebidos = {}

    def criar_chamado(conexao, usuario, dados):
        recebidos.update(usuario=usuario, dados=dados)
        return {"id_atendimento": id_atendimento, "protocolo": "AT-1"}

    monkeypatch.setattr(modulo_ferramentas.cliente, "criar_chamado", criar_chamado)
    argumentos = {
        "motivo": "Troca de tamanho",
        "resumo": "Cliente quer trocar a camisa M por G.",
        "categoria": "troca_devolucao",
    }
    provedor = ProvedorFalso(
        RespostaProvedor(texto="Passei para a equipe."),
        chamar=[("transferir_para_atendente", argumentos)],
    )
    resposta, _, _ = _enviar(repo, "quero falar com uma pessoa", provedor)
    assert resposta["status"] == "com_atendente"
    assert resposta["id_atendimento"] == id_atendimento
    conversa = repo.conversas[resposta["id_conversa"]]
    assert (conversa["status"], conversa["id_atendimento"]) == ("com_atendente", id_atendimento)
    # O chamado e aberto para o cliente do token, nao para quem o modelo disser.
    assert recebidos["usuario"] is CLIENTE
    assert recebidos["dados"] == {
        "assunto": "Troca de tamanho",
        "categoria": "troca_devolucao",
        "descricao": argumentos["resumo"],
    }
