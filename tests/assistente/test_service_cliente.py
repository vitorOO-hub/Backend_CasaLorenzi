"""Fluxo do assistente: repositorio em memoria e provedor falso (sem rede, sem banco)."""

from datetime import datetime
from uuid import UUID, uuid4

import pytest

from app.assistente.cliente import service
from app.assistente.cliente.erros import (
    ConversaComAtendente,
    ConversaNaoEncontrada,
    LimiteDiarioDoAssistente,
)
from app.assistente.cliente.ferramentas import Ferramentas
from app.assistente.cliente.provedor import ChamadaFeita, ErroProvedor, RespostaProvedor
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


class ChamadosFalsos:
    """Faz o papel de app.cliente.service.criar_chamado e guarda o que a equipe receberia."""

    def __init__(self):
        self.abertos: list[dict] = []
        self.quebrar = False

    def criar_chamado(self, conexao, usuario, dados):
        if self.quebrar:
            raise RuntimeError("banco fora")
        chamado = {"id_atendimento": uuid4(), "protocolo": f"AT-{len(self.abertos) + 1}"}
        self.abertos.append({"usuario": usuario, **dados, **chamado})
        return chamado


@pytest.fixture
def chamados(monkeypatch):
    falsos = ChamadosFalsos()
    monkeypatch.setattr(service.passagem.cliente, "criar_chamado", falsos.criar_chamado)
    # Sem lojas cadastradas: chamado na fila geral e sem aviso de horario.
    monkeypatch.setattr(service.cliente_repositorio, "listar_lojas", lambda conexao: [])
    return falsos


@pytest.fixture
def repo(monkeypatch, chamados):
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


def _passou_para_equipe(resposta, repo, chamados):
    assert resposta["resposta"] == service.TEXTO_PASSADO_PARA_EQUIPE
    assert resposta["status"] == "com_atendente" and resposta["sem_resposta"] is True
    (chamado,) = chamados.abertos
    assert resposta["id_atendimento"] == chamado["id_atendimento"]
    conversa = repo.conversas[resposta["id_conversa"]]
    assert (conversa["status"], conversa["id_atendimento"]) == (
        "com_atendente",
        chamado["id_atendimento"],
    )
    return chamado


def test_dado_sem_consulta_nao_chega_ao_cliente_e_vai_para_a_equipe(repo, chamados):
    provedor = ProvedorFalso(RespostaProvedor(texto="Voce tem uns 300 pontos."))
    resposta, _, _ = _enviar(repo, "quantos pontos eu tenho?", provedor)
    chamado = _passou_para_equipe(resposta, repo, chamados)
    assert "300" not in resposta["resposta"]
    assert "nao o consultou" in chamado["descricao"]
    assert "Cliente: quantos pontos eu tenho?" in chamado["descricao"]
    assert chamado["usuario"] is CLIENTE


@pytest.mark.parametrize(
    "resposta_modelo",
    [RespostaProvedor(texto="  "), RespostaProvedor(texto="x", concluida=False)],
)
def test_resposta_vazia_ou_rodadas_esgotadas_vao_para_a_equipe(repo, chamados, resposta_modelo):
    resposta, _, _ = _enviar(repo, "oi", ProvedorFalso(resposta_modelo))
    _passou_para_equipe(resposta, repo, chamados)


def test_consulta_que_falhou_vai_para_a_equipe(repo, chamados, monkeypatch):
    def quebra(self, args):
        raise RuntimeError("banco fora")

    monkeypatch.setattr(Ferramentas, "_consultar_pedidos", quebra)
    provedor = ProvedorFalso(
        RespostaProvedor(texto="Nao consegui ver seus pedidos."), chamar=[("consultar_pedidos", {})]
    )
    resposta, _, _ = _enviar(repo, "cade meu pedido?", provedor)
    chamado = _passou_para_equipe(resposta, repo, chamados)
    assert "consulta ao sistema falhou" in chamado["descricao"]


def test_a_equipe_recebe_a_conversa_inteira(repo, chamados):
    conexao = ConexaoFalsa()
    conversa = service.iniciar_conversa(conexao, CLIENTE)["id_conversa"]
    repo.gravar_mensagem(conexao, conversa, "usuario", "Comprei uma camisa azul M no dia 10.")
    repo.gravar_mensagem(conexao, conversa, "assistente", "Entendi. Qual o problema?")
    provedor = ProvedorFalso(erro=ErroProvedor("gemini", "tempo esgotado"))
    resposta, _, _ = _enviar(repo, "Ela veio com a costura aberta.", provedor, conversa=conversa)
    chamado = _passou_para_equipe(resposta, repo, chamados)
    descricao = chamado["descricao"]
    assert (
        descricao.index("Cliente: Comprei uma camisa azul M")
        < descricao.index("Assistente: Entendi.")
        < descricao.index("Cliente: Ela veio com a costura aberta.")
    )
    assert chamado["assunto"] == "Assistente do site: Ela veio com a costura aberta."
    assert chamado["categoria"] == "outro"


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
def test_configuracao_quebrada_so_avisa_sem_fallback_e_sem_chamado(
    repo, chamados, configuracoes, estado
):
    # A chave do Gemini existe, mas a rota rapida nao pode cair nele em silencio.
    resposta, fabricados, _ = _enviar(repo, "oi, tudo bem?", configuracoes=configuracoes)
    assert fabricados == []
    assert resposta["resposta"] == service.TEXTO_INDISPONIVEL
    assert resposta["status"] == "ativa" and resposta["sem_resposta"] is True
    # Assistente desligado nao enche a fila da equipe.
    assert chamados.abertos == []
    assert _assistente(repo)["dados"]["estado"] == estado


def test_erro_do_provedor_passa_para_a_equipe_sem_trocar_de_modelo(repo, chamados):
    provedor = ProvedorFalso(erro=ErroProvedor("groq", "resposta de erro do provedor", 503))
    resposta, fabricados, _ = _enviar(repo, "oi, tudo bem?", provedor)
    assert len(fabricados) == 1
    _passou_para_equipe(resposta, repo, chamados)
    gravada = _assistente(repo)
    assert gravada["dados"]["erro"] == "resposta de erro do provedor"
    assert gravada["dados"]["status_http"] == 503
    assert [m["autor"] for m in repo.mensagens] == ["usuario", "assistente"]


def test_chave_ausente_na_fabrica_tambem_so_avisa(repo, chamados):
    conexao = ConexaoFalsa()
    conversa = service.iniciar_conversa(conexao, CLIENTE)["id_conversa"]

    def fabrica(destino, cfg):
        raise ErroProvedor(destino.provedor, "chave ausente")

    resposta = service.enviar_mensagem(
        conexao, CLIENTE, conversa, "oi", configuracoes=_settings(), fabrica=fabrica
    )
    assert resposta["resposta"] == service.TEXTO_INDISPONIVEL
    assert chamados.abertos == []


def test_se_nem_o_chamado_abre_o_cliente_e_orientado(repo, chamados):
    chamados.quebrar = True
    provedor = ProvedorFalso(erro=ErroProvedor("groq", "tempo esgotado"))
    resposta, _, conexao = _enviar(repo, "oi, tudo bem?", provedor)
    assert resposta["resposta"] == service.TEXTO_FALHA
    assert resposta["status"] == "ativa" and resposta["id_atendimento"] is None
    assert _assistente(repo)["dados"]["passagem"] == "falhou"
    assert conexao.rollbacks == 1


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


def test_transferencia_pedida_pelo_modelo_leva_resumo_e_conversa(repo, chamados):
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
    assert resposta["resposta"] == "Passei para a equipe."
    (chamado,) = chamados.abertos
    assert resposta["id_atendimento"] == chamado["id_atendimento"]
    # O chamado e aberto para o cliente do token, nao para quem o modelo disser.
    assert chamado["usuario"] is CLIENTE
    assert (chamado["assunto"], chamado["categoria"]) == ("Troca de tamanho", "troca_devolucao")
    assert "Resumo do assistente: Cliente quer trocar a camisa M por G." in chamado["descricao"]
    assert "Cliente: quero falar com uma pessoa" in chamado["descricao"]


# ------------------------------------------------------------------ politicas, loja e horario


def test_politica_respondida_de_memoria_vai_para_a_equipe(repo, chamados):
    provedor = ProvedorFalso(RespostaProvedor(texto="Voce pode trocar em ate 60 dias."))
    resposta, _, _ = _enviar(repo, "qual o prazo para troca?", provedor)
    chamado = _passou_para_equipe(resposta, repo, chamados)
    assert "60 dias" not in resposta["resposta"]
    assert "politica da loja" in chamado["descricao"]


def test_politica_respondida_com_o_documento_chega_ao_cliente(repo, chamados):
    provedor = ProvedorFalso(
        RespostaProvedor(texto="A troca pode ser feita em ate 30 dias."),
        chamar=[("consultar_politica", {"tema": "trocas"})],
    )
    resposta, _, _ = _enviar(repo, "qual o prazo para troca?", provedor)
    assert resposta["resposta"] == "A troca pode ser feita em ate 30 dias."
    assert resposta["status"] == "ativa" and chamados.abertos == []


SEMANA = {
    d: {"abre": "10:00", "fecha": "19:00"} for d in ("seg", "ter", "qua", "qui", "sex", "sab")
}


@pytest.fixture
def rede(monkeypatch):
    lojas_da_rede = [
        {"id_loja": uuid4(), "nome": "casa lorenzi ibirapuera", "horario_funcionamento": SEMANA},
        {"id_loja": uuid4(), "nome": "vulto batel", "horario_funcionamento": SEMANA},
    ]
    monkeypatch.setattr(service.cliente_repositorio, "listar_lojas", lambda conexao: lojas_da_rede)
    return lojas_da_rede


class _Relogio:
    def __init__(self, agora):
        self.agora = agora

    def now(self, tz=None):
        return self.agora


def test_chamado_vai_para_a_loja_que_o_cliente_citou(repo, chamados, rede, monkeypatch):
    from app.cliente.vencimento_pontos import SP

    monkeypatch.setattr(service, "datetime", _Relogio(datetime(2026, 10, 28, 12, 0, tzinfo=SP)))
    provedor = ProvedorFalso(erro=ErroProvedor("groq", "tempo esgotado"))
    resposta, _, _ = _enviar(repo, "comprei na loja do Ibirapuera e a peca veio rasgada", provedor)
    chamado = _passou_para_equipe(resposta, repo, chamados)
    assert chamado["id_loja"] == rede[0]["id_loja"]
    assert "Loja: casa lorenzi ibirapuera (citada pelo cliente)" in chamado["descricao"]


def test_sem_loja_citada_vai_para_a_fila_geral(repo, chamados, rede, monkeypatch):
    from app.cliente.vencimento_pontos import SP

    monkeypatch.setattr(service, "datetime", _Relogio(datetime(2026, 10, 28, 12, 0, tzinfo=SP)))
    provedor = ProvedorFalso(erro=ErroProvedor("groq", "tempo esgotado"))
    resposta, _, _ = _enviar(repo, "minha peca veio rasgada", provedor)
    chamado = _passou_para_equipe(resposta, repo, chamados)
    assert "id_loja" not in chamado
    assert "Loja: nao identificada (fila geral)" in chamado["descricao"]


def test_fora_do_horario_a_resposta_diz_quando_a_equipe_volta(repo, chamados, rede, monkeypatch):
    from app.cliente.vencimento_pontos import SP

    monkeypatch.setattr(service, "datetime", _Relogio(datetime(2026, 10, 28, 22, 0, tzinfo=SP)))
    provedor = ProvedorFalso(erro=ErroProvedor("groq", "tempo esgotado"))
    resposta, _, _ = _enviar(repo, "minha peca veio rasgada", provedor)
    assert resposta["resposta"].startswith(service.TEXTO_PASSADO_PARA_EQUIPE)
    assert resposta["resposta"].endswith("responde amanhã a partir das 10:00.")
    assert resposta["status"] == "com_atendente"


def test_pergunta_de_volta_sem_numero_pode_seguir_mesmo_em_tema_de_politica(repo, chamados):
    provedor = ProvedorFalso(RespostaProvedor(texto="Poxa! Qual o numero do pedido?"))
    resposta, _, _ = _enviar(repo, "minha camisa veio com defeito", provedor)
    assert resposta["resposta"] == "Poxa! Qual o numero do pedido?"
    assert chamados.abertos == []
    # Afirmar sem consultar continua indo para a equipe, com ou sem numero.
    provedor = ProvedorFalso(RespostaProvedor(texto="Sim, aceitamos Pix."))
    resposta, _, _ = _enviar(repo, "aceita pix?", provedor)
    assert resposta["status"] == "com_atendente"
