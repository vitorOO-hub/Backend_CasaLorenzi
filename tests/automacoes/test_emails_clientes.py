"""E-mails ao cliente pelo n8n (resumo da compra, pontos a vencer, categoria), sem banco e sem rede:
o repositorio e o httpx.post viram dubles."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest

from app.automacoes import emails, repositorio, service
from app.core.config import Settings
from tests.automacoes.test_base_assistente import (  # noqa: F401
    AUTOMACOES,
    CHAVE,
    montar_cliente,
    par,
)
from tests.conftest import DATABASE_URL_TESTE

URL = "https://n8n.exemplo/webhook/casa-lorenzi-emails"
CLIENTE = uuid4()


def configuracoes(**extra):
    padrao = {"n8n_webhook_emails": URL, "chave_automacao": CHAVE}
    return Settings(_env_file=None, database_url=DATABASE_URL_TESTE, **{**padrao, **extra})


class ConexaoFalsa:
    commits = 0

    def commit(self):
        self.commits += 1


class N8nFalso:
    """Faz o papel do webhook: guarda o que recebeu e responde com o status combinado."""

    def __init__(self, status=200, erro=None):
        self.status, self.erro, self.recebidos = status, erro, []

    def __call__(self, url, json, headers, timeout):
        if self.erro:
            raise self.erro
        self.recebidos.append({"url": url, "json": json, "headers": headers})
        return httpx.Response(self.status, json={"ok": self.status < 300})


@pytest.fixture
def n8n(monkeypatch):
    falso = N8nFalso()
    monkeypatch.setattr(emails.httpx, "post", falso)
    return falso


COMPRA = {
    "id_pedido": uuid4(),
    "numero_pedido": "PD-20261029-ABCD1234",
    "criado_em": datetime(2026, 10, 29, 15, tzinfo=UTC),
    "valor_total": Decimal("449.70"),
    "valor_frete": Decimal("0"),
    "canal_venda": "loja",
    "loja": "Casa Lorenzi Centro",
    "id_usuario": CLIENTE,
    "nome": "ana souza",
    "email": "ana@exemplo.com",
    "pagamento": "Pix",
    "pontos_ganhos": 449,
    "saldo": 1200,
    "itens": [
        {
            "produto": "camisa linho",
            "cor": "azul",
            "tamanho": "M",
            "quantidade": 3,
            "preco_unitario": Decimal("149.90"),
            "imagem_url": "/img/produtos/CL-0101.jpg",
        }
    ],
}


@pytest.fixture
def avisos(monkeypatch):
    """`aviso_cliente` em memoria, com a mesma regra de reserva do SQL."""
    tabela: dict[tuple, dict] = {}

    def reservar(conexao, id_usuario, tipo, chave):
        linha = tabela.get((id_usuario, tipo, chave))
        if linha is None:
            linha = tabela[(id_usuario, tipo, chave)] = {
                "id": uuid4(),
                "status": "pendente",
                "n": 0,
            }
            return linha["id"]
        if linha["status"] == "falhou" and linha["n"] < repositorio.MAX_TENTATIVAS:
            linha["status"] = "pendente"
            return linha["id"]
        return None

    def concluir(conexao, id_aviso, erro):
        linha = next(v for v in tabela.values() if v["id"] == id_aviso)
        linha["status"], linha["n"] = ("falhou" if erro else "enviado"), linha["n"] + 1

    monkeypatch.setattr(repositorio, "reservar_aviso", reservar)
    monkeypatch.setattr(repositorio, "concluir_aviso", concluir)
    monkeypatch.setattr(repositorio, "dados_da_compra", lambda c, i: dict(COMPRA))
    return tabela


# ------------------------------------------------------------------ envio ao n8n


def test_envio_leva_a_chave_no_cabecalho_e_o_corpo(n8n):
    assert emails.enviar(configuracoes(), {"tipo": "pontos"}) is None
    recebido = n8n.recebidos[0]
    assert recebido["url"] == URL
    assert recebido["headers"] == {"X-Chave-Automacao": CHAVE}


@pytest.mark.parametrize(
    ("falso", "erro"),
    [
        (N8nFalso(status=500), "n8n respondeu 500"),
        (N8nFalso(erro=httpx.ReadTimeout("lento")), "sem resposta do n8n (ReadTimeout)"),
    ],
)
def test_erro_do_n8n_vira_falha_e_nao_estoura(monkeypatch, falso, erro):
    monkeypatch.setattr(emails.httpx, "post", falso)
    assert emails.enviar(configuracoes(), {"tipo": "pontos"}) == erro


def test_sem_url_ou_sem_chave_nada_sai(n8n):
    assert emails.enviar(configuracoes(n8n_webhook_emails=None), {"tipo": "x"})
    assert emails.enviar(configuracoes(chave_automacao=None), {"tipo": "x"})
    assert n8n.recebidos == []


# ------------------------------------------------------------------ resumo da compra


def test_resumo_da_compra_tem_itens_totais_e_pontos():
    m = emails.mensagem_da_compra(configuracoes(), COMPRA)
    assert m["tipo"] == "pos_compra"
    assert m["para"] == {"nome": "ana souza", "primeiro_nome": "Ana", "email": "ana@exemplo.com"}
    item = m["pedido"]["itens"][0]
    assert item["produto"] == "camisa linho azul M" and item["nome"] == "camisa linho"
    assert (item["quantidade"], item["preco_unitario"], item["total"]) == (3, 149.9, 449.7)
    # Foto do catalogo com o endereco completo do site.
    assert item["imagem"] == "https://projetocasalorenzi.vercel.app/img/produtos/CL-0101.jpg"
    assert m["pedido"]["total"] == 449.7
    assert m["pontos"] == {"ganhos": 449, "saldo": 1200}


def test_resumo_sai_uma_vez_e_falha_tenta_de_novo(n8n, avisos):
    conexao = ConexaoFalsa()
    assert (
        emails.enviar_resumo_da_compra(conexao, configuracoes(), COMPRA["id_pedido"]) == "enviado"
    )
    # Mesma compra de novo (checkout repetido, disparo diario): nao manda em dobro.
    assert emails.enviar_resumo_da_compra(conexao, configuracoes(), COMPRA["id_pedido"]) == (
        "ja_enviado"
    )
    assert len(n8n.recebidos) == 1


def test_resumo_que_falhou_fica_para_o_proximo_disparo(monkeypatch, avisos):
    monkeypatch.setattr(emails.httpx, "post", N8nFalso(status=500))
    conexao = ConexaoFalsa()
    assert emails.enviar_resumo_da_compra(conexao, configuracoes(), COMPRA["id_pedido"]) == "falhou"
    monkeypatch.setattr(emails.httpx, "post", N8nFalso())
    assert (
        emails.enviar_resumo_da_compra(conexao, configuracoes(), COMPRA["id_pedido"]) == "enviado"
    )


def test_cliente_sem_email_nao_recebe(n8n, avisos, monkeypatch):
    monkeypatch.setattr(repositorio, "dados_da_compra", lambda c, i: {**COMPRA, "email": None})
    assert emails.enviar_resumo_da_compra(ConexaoFalsa(), configuracoes(), uuid4()) == "sem_email"
    assert n8n.recebidos == [] and avisos == {}


def test_segundo_plano_sem_n8n_nem_abre_o_banco(monkeypatch):
    monkeypatch.setattr(emails, "abrir_conexao", lambda c: pytest.fail("abriu o banco"))
    emails.resumo_da_compra_em_segundo_plano(configuracoes(n8n_webhook_emails=None), uuid4())


def test_segundo_plano_nunca_estoura_na_venda(monkeypatch):
    def quebra(c):
        raise RuntimeError("banco fora")

    monkeypatch.setattr(emails, "abrir_conexao", quebra)
    emails.resumo_da_compra_em_segundo_plano(configuracoes(), uuid4())


# ------------------------------------------------------------------ pontos e categoria


@pytest.mark.parametrize(
    ("creditos", "perto"),
    [(1599, False), (1600, True), (1999, True), (4000, True), (3999, False), (10000, False)],
)
def test_perto_da_proxima_categoria(creditos, perto):
    from app.cliente.repositorio import situacao_da_categoria

    assert emails.perto_da_proxima(situacao_da_categoria(creditos)) is perto


A_VENCER = {
    "id_cliente": CLIENTE,
    "nome": "ana souza",
    "email": "ana@exemplo.com",
    "telefone": None,
    "saldo": 900,
    "categoria": "bronze",
    "proxima_categoria": "prata",
    "faltam_para_proxima": 300,
    "pontos_a_vencer": 120,
    "vencimentos": [{"vence_em": datetime(2026, 11, 3, 3, tzinfo=UTC), "pontos": 120}],
}


@pytest.fixture
def disparo(monkeypatch, avisos):
    gravados = []
    monkeypatch.setattr(
        service, "clientes_a_avisar", lambda c, dias, canal: {"clientes": [dict(A_VENCER)]}
    )
    monkeypatch.setattr(repositorio, "gravar_avisos", lambda c, canal, a: gravados.append(a) or 1)
    monkeypatch.setattr(repositorio, "clientes_com_email", lambda c: [])
    monkeypatch.setattr(repositorio, "avisos_de_categoria", lambda c, chaves: set())
    monkeypatch.setattr(repositorio, "compras_a_reenviar", lambda c, limite: [])
    return gravados


def test_aviso_de_pontos_fala_dos_beneficios_da_proxima_e_registra(n8n, disparo, avisos):
    feito = emails.disparar(ConexaoFalsa(), configuracoes())
    assert feito["pontos"]["enviados"] == 1
    mensagem = n8n.recebidos[0]["json"]
    assert mensagem["tipo"] == "pontos" and mensagem["pontos"]["a_vencer"] == 120
    proxima = mensagem["categoria"]["proxima"]
    assert proxima["nome"] == "Prata" and proxima["faltam"] == 300
    assert proxima["beneficios"][0]["titulo"] == "Frete grátis acima de R$ 600"
    assert len(disparo) == 1  # lote gravado: nao avisa de novo amanha
    # Ja falou da categoria no mesmo e-mail: o aviso de categoria fica marcado como enviado.
    assert [v["status"] for k, v in avisos.items() if k[1] == "categoria"] == ["enviado"]


def test_pontos_que_falharam_nao_sao_registrados(monkeypatch, disparo):
    monkeypatch.setattr(emails.httpx, "post", N8nFalso(status=500))
    feito = emails.disparar(ConexaoFalsa(), configuracoes())
    assert feito["pontos"] == {**feito["pontos"], "enviados": 0, "falhas": 1}
    assert disparo == []


def test_simular_nao_envia_nem_grava(n8n, disparo):
    feito = emails.disparar(ConexaoFalsa(), configuracoes(), simular=True)
    assert feito["pontos"]["candidatos"] == 1
    assert n8n.recebidos == [] and disparo == []


def test_aviso_de_categoria_sai_uma_vez(n8n, disparo, monkeypatch):
    monkeypatch.setattr(service, "clientes_a_avisar", lambda c, dias, canal: {"clientes": []})
    perto = {"id_usuario": uuid4(), "nome": "bia", "email": "bia@ex.com", "saldo": 4500}
    monkeypatch.setattr(
        repositorio, "clientes_com_email", lambda c: [{**perto, "creditos_no_ano": 4200}]
    )
    assert emails.disparar(ConexaoFalsa(), configuracoes())["categoria"]["enviados"] == 1
    assert n8n.recebidos[0]["json"]["categoria"]["proxima"]["codigo"] == "ouro"
    assert emails.disparar(ConexaoFalsa(), configuracoes())["categoria"]["enviados"] == 0


# ------------------------------------------------------------------ rotas


def test_preparar_diarios_devolve_pontos_sem_gravar_nada(disparo, avisos):
    pronto = emails.preparar_diarios(ConexaoFalsa(), configuracoes())
    assert pronto["total"] == 1
    mensagem = pronto["emails"][0]
    assert mensagem["tipo"] == "pontos" and mensagem["para"]["email"] == "ana@exemplo.com"
    assert mensagem["confirmacao"]["chave_categoria"] == "prata:2026"
    assert disparo == [] and avisos == {}  # so o n8n confirmando grava


def test_categoria_ja_dita_no_email_de_pontos_nao_ganha_outro(disparo, monkeypatch):
    perto = {"id_usuario": CLIENTE, "nome": "ana", "email": "ana@exemplo.com", "saldo": 900}
    monkeypatch.setattr(
        repositorio, "clientes_com_email", lambda c: [{**perto, "creditos_no_ano": 1700}]
    )
    pronto = emails.preparar_diarios(ConexaoFalsa(), configuracoes())
    assert [m["tipo"] for m in pronto["emails"]] == ["pontos"]


def test_preparar_diarios_inclui_categoria_de_quem_nao_tem_pontos(disparo, monkeypatch):
    monkeypatch.setattr(service, "clientes_a_avisar", lambda c, dias, canal: {"clientes": []})
    perto = {"id_usuario": uuid4(), "nome": "bia", "email": "bia@ex.com", "saldo": 4500}
    monkeypatch.setattr(
        repositorio, "clientes_com_email", lambda c: [{**perto, "creditos_no_ano": 4200}]
    )
    pronto = emails.preparar_diarios(ConexaoFalsa(), configuracoes())
    assert [m["tipo"] for m in pronto["emails"]] == ["categoria"]
    assert pronto["emails"][0]["confirmacao"]["chave_categoria"].startswith("ouro:")


def test_registrar_enviados_grava_o_lote_e_marca_a_categoria(disparo, avisos):
    pronto = emails.preparar_diarios(ConexaoFalsa(), configuracoes())
    confirmacao = pronto["emails"][0]["confirmacao"]
    from app.automacoes.schemas import EmailsEnviados

    dados = EmailsEnviados.model_validate({"enviados": [confirmacao]})
    assert emails.registrar_enviados(ConexaoFalsa(), dados.enviados) == {
        "recebidos": 1,
        "gravados": 1,
    }
    assert len(disparo) == 1
    assert [v["status"] for k, v in avisos.items() if k[1] == "categoria"] == ["enviado"]
    # Repetir a confirmacao nao duplica o aviso de categoria.
    emails.registrar_enviados(ConexaoFalsa(), dados.enviados)
    assert len([k for k in avisos if k[1] == "categoria"]) == 1


def test_rotas_do_disparo_diario_exigem_a_chave(par, monkeypatch):  # noqa: F811
    monkeypatch.setattr(
        emails,
        "preparar_diarios",
        lambda c, cfg: {"total": 0, "emails": [], "resumos_reenviados": {}},
    )
    cliente = montar_cliente(par, chave_automacao=CHAVE)
    assert cliente.post(AUTOMACOES + "/emails-diarios").status_code == 401
    cabecalho = {"X-Chave-Automacao": CHAVE}
    assert cliente.post(AUTOMACOES + "/emails-diarios", headers=cabecalho).json()["total"] == 0
    vazio = cliente.post(
        AUTOMACOES + "/emails-diarios/enviados", headers=cabecalho, json={"enviados": []}
    )
    assert vazio.status_code == 422


def test_disparo_exige_a_chave_e_o_n8n_configurado(par, monkeypatch):  # noqa: F811
    monkeypatch.setattr(emails, "disparar", lambda c, cfg, simular: {"simulado": simular})
    sem_n8n = montar_cliente(par, chave_automacao=CHAVE)
    assert sem_n8n.post(AUTOMACOES + "/disparar-emails").status_code == 401
    cabecalho = {"X-Chave-Automacao": CHAVE}
    assert sem_n8n.post(AUTOMACOES + "/disparar-emails", headers=cabecalho).status_code == 503
    simulado = sem_n8n.post(AUTOMACOES + "/disparar-emails?simular=true", headers=cabecalho)
    assert simulado.json() == {"simulado": True}
    com_n8n = montar_cliente(par, chave_automacao=CHAVE, n8n_webhook_emails=URL)
    assert com_n8n.post(AUTOMACOES + "/disparar-emails", headers=cabecalho).status_code == 200


@pytest.mark.parametrize(
    ("email", "valido"),
    [
        ("ana@exemplo.com", True),
        ("Ana.Souza+loja@Exemplo.com.br", True),
        ("", False),
        (None, False),
        ("sem-arroba.com", False),
        ("ana@semponto", False),
        ("ana @exemplo.com", False),
    ],
)
def test_so_envia_para_email_valido(email, valido):
    assert emails.email_valido(email) is valido


def test_email_invalido_no_cadastro_nao_tenta_enviar(n8n, avisos, monkeypatch):
    monkeypatch.setattr(repositorio, "dados_da_compra", lambda c, i: {**COMPRA, "email": "ana@"})
    assert emails.enviar_resumo_da_compra(ConexaoFalsa(), configuracoes(), uuid4()) == "sem_email"
    assert n8n.recebidos == []
