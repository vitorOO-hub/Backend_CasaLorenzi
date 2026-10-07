"""Supabase Realtime do chat: publicacao, canais privados e a tabela de leitura fechada ao front."""

import pytest

from tests.banco.apoio import como, e_erro, tenta
from tests.banco.fabrica import Usuario

pytestmark = pytest.mark.banco

INSERIR_BROADCAST = (
    "INSERT INTO realtime.messages (topic, extension) VALUES (realtime.topic(), 'broadcast')"
)
INSERIR_OUTRA_EXTENSAO = (
    "INSERT INTO realtime.messages (topic, extension) VALUES (realtime.topic(), 'postgres_changes')"
)
INSERIR_X = "INSERT INTO realtime.messages (topic, extension) VALUES ('x', 'broadcast')"

POLITICAS = [
    ("chat - receber presenca e digitacao do chamado", "SELECT"),
    ("chat - enviar presenca e digitacao do chamado", "INSERT"),
]


def como_usuario(conn, usuario: Usuario, topico: str | None = None):
    papel = {"diretor": "admin"}.get(usuario.tipo, usuario.tipo)
    papel = None if papel == "cliente" else papel
    loja = None if papel in (None, "admin") else usuario.loja
    contexto = como(conn, sub=usuario.auth, papel=papel, loja=loja)
    return contexto


def com_topico(conn, topico):
    """O Realtime informa o canal pela configuracao realtime.topic antes de checar a policy."""
    conn.execute("SELECT set_config('realtime.topic', %s, true)", (topico,))


@pytest.fixture
def cenario(conn, fab):
    loja_a, loja_b = fab.loja(), fab.loja()
    dono, outro = fab.usuario("cliente"), fab.usuario("cliente")
    atendimento = fab.atendimento(cliente=dono, loja=loja_a)
    return {
        "topico": f"chamado:{atendimento}",
        "atendimento": atendimento,
        "dono": dono,
        "outro": outro,
        "ate_a": fab.usuario("atendente", loja=loja_a),
        "ger_a": fab.usuario("gerente_loja", loja=loja_a),
        "ate_b": fab.usuario("atendente", loja=loja_b),
        "admin": fab.usuario("diretor"),
    }


# ------------------------------------------------------------------ Postgres Changes


@pytest.mark.parametrize("tabela", ["mensagem", "atendimento"])
def test_tabelas_do_chat_estao_na_publicacao_do_realtime(conn, tabela):
    achada = conn.execute(
        "SELECT count(*) FROM pg_publication_tables "
        "WHERE pubname = 'supabase_realtime' AND schemaname = 'public' AND tablename = %s",
        (tabela,),
    ).fetchone()[0]
    assert achada == 1


def test_realtime_so_entrega_mensagem_que_o_rls_deixa_ler(conn, fab, cenario):
    """Postgres Changes respeita o RLS: o que a pessoa nao le por SELECT, ela nao recebe ao vivo."""
    fab.mensagem(atendimento=cenario["atendimento"], remetente=cenario["dono"], texto="oi")
    quem_ve = {"dono": 1, "ate_a": 1, "ger_a": 1, "admin": 1, "outro": 0, "ate_b": 0}
    for nome, esperado in quem_ve.items():
        with como_usuario(conn, cenario[nome]):
            linhas = tenta(conn, "SELECT id_mensagem FROM mensagem")
        assert len(linhas) == esperado, nome


# ------------------------------------------------------------------ canais privados


def test_policies_do_canal_existem(conn):
    achadas = conn.execute(
        "SELECT policyname, cmd FROM pg_policies "
        "WHERE schemaname = 'realtime' AND tablename = 'messages'"
    ).fetchall()
    assert set(achadas) == set(POLITICAS)


@pytest.mark.parametrize(
    ("quem", "entra"),
    [
        ("dono", True),
        ("ate_a", True),
        ("ger_a", True),
        ("admin", True),
        ("outro", False),
        ("ate_b", False),
    ],
)
@pytest.mark.parametrize("extensao", ["broadcast", "presence"])
def test_so_quem_ve_o_chamado_envia_digitando_e_presenca(conn, cenario, quem, entra, extensao):
    with como_usuario(conn, cenario[quem]):
        com_topico(conn, cenario["topico"])
        resultado = tenta(
            conn,
            "INSERT INTO realtime.messages (topic, extension) VALUES (realtime.topic(), %s)",
            (extensao,),
        )
    assert (resultado == []) is entra, quem


@pytest.mark.parametrize("quem", ["dono", "ate_a", "ger_a", "admin"])
def test_quem_ve_o_chamado_tambem_recebe_o_canal(conn, cenario, quem):
    conn.execute(
        "INSERT INTO realtime.messages (topic, extension) VALUES (%s, 'broadcast')",
        (cenario["topico"],),
    )
    with como_usuario(conn, cenario[quem]):
        com_topico(conn, cenario["topico"])
        assert len(tenta(conn, "SELECT id FROM realtime.messages")) == 1


@pytest.mark.parametrize("quem", ["outro", "ate_b"])
def test_quem_nao_ve_o_chamado_nao_recebe_o_canal(conn, cenario, quem):
    conn.execute(
        "INSERT INTO realtime.messages (topic, extension) VALUES (%s, 'broadcast')",
        (cenario["topico"],),
    )
    with como_usuario(conn, cenario[quem]):
        com_topico(conn, cenario["topico"])
        assert tenta(conn, "SELECT id FROM realtime.messages") == []


@pytest.mark.parametrize(
    "topico",
    [
        "chamado:abc",
        "chamado:",
        "sala:00000000-0000-0000-0000-000000000001",
        "chamado:00000000-0000-0000-0000-000000000001:extra",
        "CHAMADO:00000000-0000-0000-0000-000000000001",
        "chamado:00000000-0000-0000-0000-000000000001' OR true --",
    ],
)
def test_topico_fora_do_formato_nunca_e_liberado(conn, cenario, topico):
    with como_usuario(conn, cenario["admin"]):
        com_topico(conn, topico)
        resultado = tenta(
            conn,
            INSERIR_BROADCAST,
        )
    assert e_erro(resultado)


def test_chamado_que_nao_existe_nao_libera_canal_nem_para_o_admin(conn, cenario):
    with como_usuario(conn, cenario["admin"]):
        com_topico(conn, "chamado:00000000-0000-0000-0000-000000000009")
        resultado = tenta(
            conn,
            INSERIR_BROADCAST,
        )
    assert e_erro(resultado)


def test_extensao_que_nao_e_broadcast_nem_presence_e_recusada(conn, cenario):
    with como_usuario(conn, cenario["ate_a"]):
        com_topico(conn, cenario["topico"])
        resultado = tenta(
            conn,
            INSERIR_OUTRA_EXTENSAO,
        )
    assert e_erro(resultado)


def test_anonimo_nao_usa_o_canal(conn, cenario):
    with como(conn, role="anon"):
        com_topico(conn, cenario["topico"])
        assert e_erro(tenta(conn, "SELECT 1 FROM realtime.messages"))
        assert e_erro(
            tenta(
                conn, "INSERT INTO realtime.messages (topic, extension) VALUES ('x', 'broadcast')"
            )
        )


# ------------------------------------------------------------------ leitura fechada ao front


def test_chamado_leitura_tem_rls_forcado(conn):
    ligado, forcado = conn.execute(
        "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
        "WHERE relname = 'chamado_leitura' AND relnamespace = 'public'::regnamespace"
    ).fetchone()
    assert ligado and forcado


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_front_nao_le_nem_escreve_a_leitura(conn, role):
    with como(conn, role=role):
        assert e_erro(tenta(conn, "SELECT 1 FROM chamado_leitura"))
        assert e_erro(tenta(conn, "DELETE FROM chamado_leitura"))
        assert e_erro(tenta(conn, "UPDATE chamado_leitura SET lida_ate = now()"))


def test_apagar_o_chamado_apaga_a_leitura(conn, fab, cenario):
    leitor = cenario["ate_a"]
    conn.execute(
        "INSERT INTO chamado_leitura (id_usuario, id_atendimento) VALUES (%s, %s)",
        (leitor.id, cenario["atendimento"]),
    )
    conn.execute("DELETE FROM atendimento WHERE id_atendimento = %s", (cenario["atendimento"],))
    assert conn.execute("SELECT count(*) FROM chamado_leitura").fetchone()[0] == 0
