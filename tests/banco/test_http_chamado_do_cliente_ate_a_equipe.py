# ruff: noqa: E501  (linhas de teste com URLs e payloads)
"""Pela API de verdade (token, papel, vigencia): o chamado que o cliente abre chega a quem deve atender.

Cobre o caminho inteiro: cliente abre -> fila e caixa de conversas da equipe da loja certa (e so dela)
-> a equipe responde -> o cliente ve a resposta -> o cliente escreve de volta -> resolver fecha o canal.
"""

from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.core import vigencia
from app.core.config import Settings
from app.main import criar_app
from tests.auth_util import SUPABASE_URL, ParDeChaves, provedor_para

pytestmark = pytest.mark.banco

CLIENTE = "/api/v1/cliente"
FILA = "/api/v1/painel/atendimentos"
CHAT = "/api/v1/painel/chat/conversas"


def _usuario(pg, tipo, nome, loja=None, *, com_endereco=False):
    auth = uuid4()
    endereco = ("Rua A", "Centro", "10", "01001000") if com_endereco else (None,) * 4
    pg.execute(
        "INSERT INTO usuario (id_tipo_usuario, id_loja, auth_user_id, nome, email, rua, bairro,"
        " numero_endereco, cep) VALUES ((SELECT id_tipo_usuario FROM tipo_usuario WHERE codigo = %s),"
        " %s, %s, %s, %s, %s, %s, %s, %s)",
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
    """Duas lojas, equipe de cada uma, dois clientes e um pedido da loja B. Limpa tudo no fim."""
    monkeypatch.setattr(vigencia, "ATIVA", True)
    vigencia._conferidos.clear()
    with psycopg.connect(banco_migrado, autocommit=True) as pg:
        lojas = [
            pg.execute(
                "INSERT INTO loja (codigo, nome, ativa) VALUES (%s, %s, true) RETURNING id_loja",
                (f"E{uuid4().hex[:8]}", nome),
            ).fetchone()[0]
            for nome in ("Loja A", "Loja B")
        ]
        a, b = lojas
        quem = {
            "atendente_a": (_usuario(pg, "atendente", "Atendente A", a), "atendente", a),
            "atendente_b": (_usuario(pg, "atendente", "Atendente B", b), "atendente", b),
            "gerente_a": (_usuario(pg, "gerente_loja", "Gerente A", a), "gerente_loja", a),
            "admin": (_usuario(pg, "diretor", "Admin Rede"), "admin", None),
            "cliente": (_usuario(pg, "cliente", "Cliente Um", com_endereco=True), None, None),
            "outro": (_usuario(pg, "cliente", "Cliente Dois", com_endereco=True), None, None),
        }
        cliente_id = pg.execute(
            "SELECT id_usuario FROM usuario WHERE auth_user_id = %s", (quem["cliente"][0],)
        ).fetchone()[0]
        pedido_b = pg.execute(
            "INSERT INTO pedido (numero_pedido, id_loja, id_cliente, id_status_pedido) VALUES "
            "(%s, %s, %s, (SELECT id_status_pedido FROM status_pedido WHERE codigo = 'pago'))"
            " RETURNING id_pedido",
            (f"PD-{uuid4().hex[:8]}", b, cliente_id),
        ).fetchone()[0]

        par = ParDeChaves()
        app = criar_app(
            Settings(_env_file=None, database_url=banco_migrado, supabase_url=SUPABASE_URL)
        )
        app.state.provedor_chaves = provedor_para(par)
        http = TestClient(app)

        def como(nome):
            auth, papel, loja = quem[nome]
            claims = {"sub": str(auth)}
            if papel:
                claims["papel"] = papel
            if loja:
                claims["loja_id"] = str(loja)
            return {"Authorization": f"Bearer {par.emitir(**claims)}"}

        yield http, como, {"a": a, "b": b, "pedido_b": pedido_b}, pg
        auths = [v[0] for v in quem.values()]
        dos_clientes = (
            "SELECT id_atendimento FROM atendimento WHERE id_cliente IN"
            " (SELECT id_usuario FROM usuario WHERE auth_user_id = ANY(%s))"
        )
        for tabela in ("mensagem", "chamado_leitura", "atendimento_item"):
            pg.execute(f"DELETE FROM {tabela} WHERE id_atendimento IN ({dos_clientes})", (auths,))  # nosec B608
        pg.execute(f"DELETE FROM atendimento WHERE id_atendimento IN ({dos_clientes})", (auths,))  # nosec B608
        pg.execute("DELETE FROM pedido WHERE id_pedido = %s", (pedido_b,))
        pg.execute("DELETE FROM usuario WHERE auth_user_id = ANY(%s)", (auths,))
        pg.execute("DELETE FROM loja WHERE id_loja = ANY(%s)", (lojas,))
    vigencia._conferidos.clear()


def _abrir(http, como, **extra):
    corpo = {"assunto": "Defeito no zíper", "categoria": "produto", "descricao": "O zíper quebrou."}
    r = http.post(f"{CLIENTE}/chamados", json={**corpo, **extra}, headers=como("cliente"))
    assert r.status_code == 201, r.text
    return r.json()


def _protocolos(http, headers):
    r = http.get(FILA, headers=headers)
    assert r.status_code == 200, r.text
    return {c["protocolo"] for c in r.json()["itens"]}


def test_chamado_da_loja_a_aparece_para_a_equipe_da_a_e_nao_para_a_b(cena):
    http, como, ids, _ = cena
    chamado = _abrir(http, como, id_loja=str(ids["a"]))
    proto = chamado["protocolo"]
    assert proto in _protocolos(http, como("atendente_a"))
    assert proto in _protocolos(http, como("gerente_a"))
    assert proto in _protocolos(http, como("admin"))
    assert proto not in _protocolos(http, como("atendente_b"))
    # E a caixa de conversas (o chat) mostra a mesma coisa.
    caixa = http.get(CHAT, headers=como("atendente_a")).json()["itens"]
    assert proto in {c["protocolo"] for c in caixa}
    caixa_b = http.get(CHAT, headers=como("atendente_b")).json()["itens"]
    assert proto not in {c["protocolo"] for c in caixa_b}
    resumo = http.get(f"{FILA}/resumo", headers=como("atendente_a")).json()
    assert resumo["sem_resposta"] >= 1


def test_chamado_sem_loja_aparece_para_a_equipe_de_todas_as_lojas(cena):
    http, como, _, _ = cena
    proto = _abrir(http, como)["protocolo"]
    assert proto in _protocolos(http, como("atendente_a"))
    assert proto in _protocolos(http, como("atendente_b"))


def test_chamado_com_pedido_vai_para_a_loja_do_pedido(cena):
    http, como, ids, _ = cena
    proto = _abrir(http, como, id_pedido=str(ids["pedido_b"]))["protocolo"]
    assert proto in _protocolos(http, como("atendente_b"))
    assert proto not in _protocolos(http, como("atendente_a"))


def test_resposta_da_equipe_chega_ao_cliente_e_a_mensagem_dele_volta_para_a_equipe(cena):
    http, como, ids, _ = cena
    chamado = _abrir(http, como, id_loja=str(ids["a"]))
    id_ = chamado["id_atendimento"]
    r = http.post(
        f"{CHAT}/{id_}/mensagens", json={"texto": "Vamos trocar!"}, headers=como("atendente_a")
    )
    assert r.status_code in (200, 201), r.text
    do_cliente = http.get(f"{CLIENTE}/chamados/{id_}/mensagens", headers=como("cliente")).json()
    textos = [m["texto"] for m in do_cliente]
    assert textos == ["O zíper quebrou.", "Vamos trocar!"]
    # O cliente responde e a equipe recebe pelo cursor (e o contador de nao lidas sobe).
    cursor = http.get(f"{CHAT}/{id_}/mensagens", headers=como("atendente_a")).json()
    ultima = cursor["ultimo_id_mensagem"]
    r = http.post(
        f"{CLIENTE}/chamados/{id_}/mensagens", json={"texto": "Obrigado"}, headers=como("cliente")
    )
    assert r.status_code in (200, 201), r.text
    novas = http.get(
        f"{CHAT}/{id_}/mensagens", params={"apos": ultima}, headers=como("atendente_a")
    ).json()
    assert [m["texto"] for m in novas["mensagens"]] == ["Obrigado"]
    nao_lidas = http.get(CHAT, headers=como("atendente_a")).json()["itens"]
    assert [c for c in nao_lidas if c["protocolo"] == chamado["protocolo"]][0]["nao_lidas"] >= 1


def test_equipe_de_outra_loja_nao_le_nem_responde(cena):
    http, como, ids, _ = cena
    id_ = _abrir(http, como, id_loja=str(ids["a"]))["id_atendimento"]
    assert http.get(f"{CHAT}/{id_}/mensagens", headers=como("atendente_b")).status_code == 404
    r = http.post(f"{CHAT}/{id_}/mensagens", json={"texto": "oi"}, headers=como("atendente_b"))
    assert r.status_code == 404


def test_outro_cliente_nao_ve_nem_escreve_no_chamado_alheio(cena):
    http, como, ids, _ = cena
    id_ = _abrir(http, como, id_loja=str(ids["a"]))["id_atendimento"]
    assert http.get(f"{CLIENTE}/chamados/{id_}", headers=como("outro")).status_code == 404
    r = http.post(f"{CLIENTE}/chamados/{id_}/mensagens", json={"texto": "x"}, headers=como("outro"))
    assert r.status_code == 404


def test_cliente_nao_entra_no_painel(cena):
    http, como, _, _ = cena
    assert http.get(FILA, headers=como("cliente")).status_code == 403
    assert http.get(CHAT, headers=como("cliente")).status_code == 403


def test_depois_de_resolvido_o_cliente_nao_escreve_mais(cena):
    http, como, ids, _ = cena
    id_ = _abrir(http, como, id_loja=str(ids["a"]))["id_atendimento"]
    assert http.post(f"{FILA}/{id_}/assumir", headers=como("atendente_a")).status_code == 200
    assert http.post(f"{FILA}/{id_}/resolver", headers=como("atendente_a")).status_code == 200
    r = http.post(
        f"{CLIENTE}/chamados/{id_}/mensagens", json={"texto": "alô"}, headers=como("cliente")
    )
    assert r.status_code == 409
