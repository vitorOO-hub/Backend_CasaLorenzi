# ruff: noqa: E501  (linhas de teste com URLs e payloads)
"""Pela API de verdade (token, banco, services): o assistente do cliente com provedor FALSO.

O provedor falso pede as ferramentas que o teste manda e devolve um texto fixo; as ferramentas rodam
de verdade contra o banco, sempre com o cliente do token. Nenhuma chamada sai para Groq ou Gemini.
"""

from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.assistente.provedor import ChamadaFeita, ErroProvedor, RespostaProvedor
from app.assistente.router import get_fabrica_provedor
from app.core import vigencia
from app.core.config import Settings
from app.main import criar_app
from tests.auth_util import SUPABASE_URL, ParDeChaves, provedor_para

pytestmark = pytest.mark.banco

BASE = "/api/v1/assistente/conversas"


class ProvedorRoteirizado:
    """Executa as ferramentas do roteiro (pelo callback real) e responde um texto fixo."""

    def __init__(self):
        self.roteiro: list[tuple[str, dict]] = []
        self.texto = "Pronto."
        self.erro: Exception | None = None
        self.resultados: list[ChamadaFeita] = []
        self.destinos = []

    def responder(self, *, executar, **_):
        if self.erro:
            raise self.erro
        self.resultados = [ChamadaFeita(n, a, executar(n, a)) for n, a in self.roteiro]
        return RespostaProvedor(
            texto=self.texto, chamadas=list(self.resultados), tokens_entrada=11, tokens_saida=7
        )


def _usuario(pg, tipo, nome, loja=None):
    auth = uuid4()
    endereco = ("Rua A", "Centro", "10", "01001000") if tipo == "cliente" else (None,) * 4
    pg.execute(
        "INSERT INTO usuario (id_tipo_usuario, id_loja, auth_user_id, nome, email, rua, bairro, numero_endereco, cep)"
        " VALUES ((SELECT id_tipo_usuario FROM tipo_usuario WHERE codigo = %s), %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            tipo,
            loja,
            auth,
            nome,
            f"{nome.lower().replace(' ', '.')}.{auth.hex[:6]}@teste.local",
            *endereco,
        ),
    )
    return auth


@pytest.fixture
def cena(banco_migrado, monkeypatch):
    monkeypatch.setattr(vigencia, "ATIVA", True)
    vigencia._conferidos.clear()
    sufixo = uuid4().hex[:6].upper()
    with psycopg.connect(banco_migrado, autocommit=True) as pg:
        loja = pg.execute(
            "INSERT INTO loja (codigo, nome, ativa, horario_funcionamento) VALUES (%s, %s, true, NULL) RETURNING id_loja",
            (f"A{sufixo}", f"Loja Assistente {sufixo}"),
        ).fetchone()[0]
        produto = pg.execute(
            "INSERT INTO produto (nome, preco_base, categoria, marca, tecido) VALUES (%s, 199, 'camisas', 'Vulto', 'linho') RETURNING id_produto",
            (f"Camisa Linho Zeta{sufixo}",),
        ).fetchone()[0]
        sku = f"ZT{sufixo}-AZ-M"
        variacao = pg.execute(
            "INSERT INTO variacao_produto (id_produto, sku, cor, tamanho, preco_venda) VALUES (%s, %s, 'azul', 'M', 199) RETURNING id_variacao",
            (produto, sku),
        ).fetchone()[0]
        pg.execute(
            "INSERT INTO estoque (id_loja, id_variacao, quantidade) VALUES (%s, %s, 4)",
            (loja, variacao),
        )
        quem = {
            "cliente": (_usuario(pg, "cliente", "Cliente Assist"), None, None),
            "outro": (_usuario(pg, "cliente", "Outro Assist"), None, None),
            "atendente": (_usuario(pg, "atendente", "Atendente Assist", loja), "atendente", loja),
        }
        par = ParDeChaves()
        app = criar_app(
            Settings(
                _env_file=None,
                database_url=banco_migrado,
                supabase_url=SUPABASE_URL,
                groq_api_key="chave-falsa-groq",
                gemini_api_key="chave-falsa-gemini",
            )
        )
        app.state.provedor_chaves = provedor_para(par)
        provedor = ProvedorRoteirizado()

        def fabrica(destino, configuracoes):
            provedor.destinos.append(destino)
            return provedor

        app.dependency_overrides[get_fabrica_provedor] = lambda: fabrica
        http = TestClient(app)

        def como(nome):
            auth, papel, id_loja = quem[nome]
            claims = {"sub": str(auth)}
            if papel:
                claims.update(papel=papel, loja_id=str(id_loja))
            return {"Authorization": f"Bearer {par.emitir(**claims)}"}

        yield (
            http,
            como,
            provedor,
            pg,
            {"sku": sku, "variacao": variacao, "sufixo": sufixo, "loja": loja},
        )

        auths = [v[0] for v in quem.values()]
        dos_clientes = "SELECT id_usuario FROM usuario WHERE auth_user_id = ANY(%s)"
        pg.execute(
            f"DELETE FROM conversa_assistente WHERE id_usuario IN ({dos_clientes})", (auths,)
        )  # nosec B608
        atendimentos = (
            f"SELECT id_atendimento FROM atendimento WHERE id_cliente IN ({dos_clientes})"  # nosec B608
        )
        for tabela in ("mensagem", "chamado_leitura", "atendimento_item"):
            pg.execute(f"DELETE FROM {tabela} WHERE id_atendimento IN ({atendimentos})", (auths,))  # nosec B608
        pg.execute(f"DELETE FROM atendimento WHERE id_atendimento IN ({atendimentos})", (auths,))  # nosec B608
        pg.execute(f"DELETE FROM carrinho WHERE id_cliente IN ({dos_clientes})", (auths,))  # nosec B608
        pg.execute("DELETE FROM usuario WHERE auth_user_id = ANY(%s)", (auths,))
        pg.execute("DELETE FROM estoque WHERE id_variacao = %s", (variacao,))
        pg.execute("DELETE FROM variacao_produto WHERE id_variacao = %s", (variacao,))
        pg.execute("DELETE FROM produto WHERE id_produto = %s", (produto,))
        pg.execute("DELETE FROM loja WHERE id_loja = %s", (loja,))
    vigencia._conferidos.clear()


def _nova(http, headers):
    r = http.post(BASE, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id_conversa"]


def _enviar(http, headers, conversa, texto):
    return http.post(f"{BASE}/{conversa}/mensagens", json={"texto": texto}, headers=headers)


def _registros(pg, conversa):
    return pg.execute(
        "SELECT autor, texto, ferramenta, dados, sem_resposta, modelo, tokens_entrada FROM mensagem_assistente"
        " WHERE id_conversa = %s ORDER BY criada_em, id_mensagem",
        (conversa,),
    ).fetchall()


def test_sem_token_nao_entra(cena):
    http, *_ = cena
    assert http.post(BASE).status_code == 401


def test_equipe_nao_usa_o_assistente_do_cliente(cena):
    http, como, *_ = cena
    assert http.post(BASE, headers=como("atendente")).status_code == 403


def test_busca_e_estoque_reais_com_ferramentas_registradas(cena):
    http, como, provedor, pg, ids = cena
    conversa = _nova(http, como("cliente"))
    provedor.roteiro = [
        ("buscar_produto", {"descricao": f"camisa linho zeta{ids['sufixo'].lower()}"}),
        ("consultar_estoque", {"sku": ids["sku"]}),
        ("info_loja", {"loja": f"assistente {ids['sufixo']}"}),
    ]
    provedor.texto = "Temos 4 unidades."
    r = _enviar(http, como("cliente"), conversa, f"tem estoque da camisa {ids['sku']}?")
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["resposta"] == "Temos 4 unidades." and corpo["sem_resposta"] is False
    busca, estoque, loja = (c.resultado for c in provedor.resultados)
    assert [v["sku"] for v in busca["pecas"][0]["variacoes"]] == [ids["sku"]]
    assert estoque["total"] == 4
    assert loja["lojas"][0]["horario_funcionamento"] is None
    autores = [(a, f) for a, _, f, *_ in _registros(pg, conversa)]
    assert autores == [
        ("usuario", None),
        ("ferramenta", "buscar_produto"),
        ("ferramenta", "consultar_estoque"),
        ("ferramenta", "info_loja"),
        ("assistente", None),
    ]
    assistente = _registros(pg, conversa)[-1]
    # Consulta direta e sem dado sensivel: rota rapida, como o roteador decide.
    assert assistente[5] == "groq:openai/gpt-oss-20b" and assistente[6] == 11
    # O historico visivel nao mostra os registros de ferramenta.
    mensagens = http.get(f"{BASE}/{conversa}", headers=como("cliente")).json()["mensagens"]
    assert [m["autor"] for m in mensagens] == ["usuario", "assistente"]


def test_pontos_e_pedidos_sao_so_do_cliente_do_token(cena):
    http, como, provedor, *_ = cena
    conversa = _nova(http, como("cliente"))
    provedor.roteiro = [("consultar_pontos", {}), ("consultar_pedidos", {})]
    assert _enviar(http, como("cliente"), conversa, "quantos pontos eu tenho?").status_code == 200
    assert provedor.destinos[-1].provedor == "gemini"  # pontos: rota precisa
    pontos, pedidos = (c.resultado for c in provedor.resultados)
    assert pontos["saldo"] == 0 and pontos["categoria"] in ("bronze", None)
    assert pedidos == {"pedidos": []}


def test_montar_carrinho_coloca_na_sacola_do_cliente(cena):
    http, como, provedor, pg, ids = cena
    conversa = _nova(http, como("cliente"))
    provedor.roteiro = [("montar_carrinho", {"sku": ids["sku"].lower(), "quantidade": 2})]
    corpo = _enviar(http, como("cliente"), conversa, "coloca na sacola por favor").json()
    assert corpo["carrinho_alterado"] is True
    sacola = http.get("/api/v1/cliente/carrinho", headers=como("cliente")).json()
    assert [(i["id_variacao"], i["quantidade"]) for i in sacola["itens"]] == [
        (str(ids["variacao"]), 2)
    ]


def test_transferencia_abre_chamado_e_trava_a_conversa(cena):
    http, como, provedor, pg, _ = cena
    conversa = _nova(http, como("cliente"))
    provedor.roteiro = [
        (
            "transferir_para_atendente",
            {
                "motivo": "Troca de tamanho",
                "resumo": "Cliente quer trocar a camisa M por G.",
                "categoria": "troca_devolucao",
            },
        )
    ]
    corpo = _enviar(http, como("cliente"), conversa, "quero falar com uma pessoa").json()
    assert corpo["status"] == "com_atendente" and corpo["id_atendimento"]
    chamado = http.get(
        f"/api/v1/cliente/chamados/{corpo['id_atendimento']}", headers=como("cliente")
    )
    assert chamado.status_code == 200 and chamado.json()["assunto"] == "Troca de tamanho"
    # Depois de passar para a equipe, o modelo nao responde mais nesta conversa.
    assert _enviar(http, como("cliente"), conversa, "oi?").status_code == 409


def test_conversa_de_outro_cliente_e_404_e_nada_e_gravado(cena):
    http, como, provedor, pg, _ = cena
    conversa = _nova(http, como("cliente"))
    assert http.get(f"{BASE}/{conversa}", headers=como("outro")).status_code == 404
    assert _enviar(http, como("outro"), conversa, "oi").status_code == 404
    assert _registros(pg, conversa) == []
    assert provedor.destinos == []


def test_pergunta_incompleta_nao_chama_o_modelo(cena):
    http, como, provedor, pg, _ = cena
    conversa = _nova(http, como("cliente"))
    corpo = _enviar(http, como("cliente"), conversa, "tem essa peca na loja?").json()
    assert provedor.destinos == []
    assert "qual peça" in corpo["resposta"]


def test_erro_do_provedor_passa_para_a_equipe_que_le_a_conversa(cena):
    http, como, provedor, pg, _ = cena
    conversa = _nova(http, como("cliente"))
    provedor.texto = "Qual o numero do pedido?"
    assert (
        _enviar(http, como("cliente"), conversa, "minha camisa veio com defeito").status_code == 200
    )
    provedor.erro = ErroProvedor("groq", "resposta de erro do provedor", 500)
    r = _enviar(http, como("cliente"), conversa, "pedido PD-77, costura aberta na manga")
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["status"] == "com_atendente" and corpo["sem_resposta"] is True
    assert "chave" not in r.text.lower()
    registros = _registros(pg, conversa)
    assert [x[0] for x in registros] == ["usuario", "assistente", "usuario", "assistente"]
    assert registros[-1][3]["status_http"] == 500 and registros[-1][4] is True
    # O chamado sem loja cai na fila geral: o atendente le a conversa sem o cliente repetir nada.
    id_ = corpo["id_atendimento"]
    lidas = http.get(f"/api/v1/painel/chat/conversas/{id_}/mensagens", headers=como("atendente"))
    assert lidas.status_code == 200, lidas.text
    (primeira,) = [m["texto"] for m in lidas.json()["mensagens"]]
    assert primeira.startswith("Chamado aberto pelo assistente do site.")
    for trecho in (
        "Cliente: minha camisa veio com defeito",
        "Assistente: Qual o numero do pedido?",
        "Cliente: pedido PD-77, costura aberta na manga",
    ):
        assert trecho in primeira
    # A conversa travou: o cliente continua pelo chamado.
    assert _enviar(http, como("cliente"), conversa, "e ai?").status_code == 409


def test_limite_diario_por_cliente(cena, monkeypatch):
    from app.assistente import service

    http, como, *_ = cena
    monkeypatch.setattr(service, "LIMITE_DIARIO_POR_CLIENTE", 2)
    conversa = _nova(http, como("cliente"))
    assert _enviar(http, como("cliente"), conversa, "oi").status_code == 200
    assert _enviar(http, como("cliente"), conversa, "oi de novo").status_code == 200
    assert _enviar(http, como("cliente"), conversa, "mais uma").status_code == 429
    # O limite e do cliente, nao da conversa nem do IP.
    outra = _nova(http, como("cliente"))
    assert _enviar(http, como("cliente"), outra, "oi").status_code == 429
    assert _enviar(http, como("outro"), _nova(http, como("outro")), "oi").status_code == 200
