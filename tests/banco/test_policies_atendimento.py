from types import SimpleNamespace

import psycopg
import pytest

from tests.banco.apoio import como, e_erro, tenta
from tests.banco.fabrica import Usuario

pytestmark = pytest.mark.banco

INSERIR_MENSAGEM = (
    "INSERT INTO mensagem (id_atendimento, id_usuario_remetente, texto) VALUES (%s, %s, 'ola')"
)
INSERIR_AVALIACAO = "INSERT INTO avaliacao_atendimento (id_atendimento, nota) VALUES (%s, 5)"


def como_usuario(conn, usuario: Usuario):
    papel = {"diretor": "admin"}.get(usuario.tipo, usuario.tipo)
    papel = None if papel == "cliente" else papel
    loja = None if papel in (None, "admin") else usuario.loja
    return como(conn, sub=usuario.auth, papel=papel, loja=loja)


def ids_visiveis(conn, usuario: Usuario, consulta: str) -> set:
    with como_usuario(conn, usuario):
        return {linha[0] for linha in conn.execute(consulta).fetchall()}


@pytest.fixture
def cenario(fab):
    loja_a, loja_b = fab.loja(), fab.loja()
    usuarios = {
        "cliente1": fab.usuario("cliente"),
        "cliente2": fab.usuario("cliente"),
        "atendente_a": fab.usuario("atendente", loja=loja_a),
        "gerente_a": fab.usuario("gerente_loja", loja=loja_a),
        "atendente_b": fab.usuario("atendente", loja=loja_b),
        "operador_a": fab.usuario("operador_estoque", loja=loja_a),
        "atendente_a_inativo": fab.usuario("atendente", loja=loja_a, ativo=False),
        "admin": fab.usuario("diretor"),
    }
    c1, c2 = usuarios["cliente1"], usuarios["cliente2"]
    atendimentos = {
        "a1": fab.atendimento(cliente=c1, loja=loja_a),
        "a2": fab.atendimento(cliente=c2, loja=loja_a),
        "a3": fab.atendimento(cliente=c1, loja=loja_b),
        "sem_loja": fab.atendimento(cliente=c1),
        "resolvido": fab.atendimento(cliente=c1, loja=loja_a, status="resolvido"),
    }
    return SimpleNamespace(usuarios=usuarios, atendimentos=atendimentos, lojas=(loja_a, loja_b))


# ---- atendimento ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("quem", "esperado"),
    [
        ("cliente1", {"a1", "a3", "sem_loja", "resolvido"}),
        ("cliente2", {"a2"}),
        ("atendente_a", {"a1", "a2", "resolvido"}),
        ("gerente_a", {"a1", "a2", "resolvido"}),
        ("atendente_b", {"a3"}),
        ("operador_a", set()),
        ("atendente_a_inativo", set()),
        ("admin", {"a1", "a2", "a3", "sem_loja", "resolvido"}),
    ],
)
def test_visibilidade_dos_atendimentos(conn, cenario, quem, esperado):
    visiveis = ids_visiveis(conn, cenario.usuarios[quem], "SELECT id_atendimento FROM atendimento")
    assert visiveis == {cenario.atendimentos[nome] for nome in esperado}


def test_anon_nao_ve_atendimentos(conn, cenario):
    with como(conn, role="anon"):
        assert e_erro(tenta(conn, "SELECT id_atendimento FROM atendimento"))


def test_itens_do_atendimento_seguem_a_visibilidade(conn, cenario, fab):
    item_pedido = fab.item_pedido(
        pedido=fab.pedido(loja=cenario.lojas[0], cliente=cenario.usuarios["cliente1"])
    )
    conn.execute(
        "INSERT INTO atendimento_item (id_atendimento, id_item_pedido) VALUES (%s, %s)",
        (cenario.atendimentos["a1"], item_pedido),
    )
    consulta = "SELECT id_atendimento FROM atendimento_item"
    assert ids_visiveis(conn, cenario.usuarios["cliente1"], consulta) == {
        cenario.atendimentos["a1"]
    }
    assert ids_visiveis(conn, cenario.usuarios["cliente2"], consulta) == set()
    assert ids_visiveis(conn, cenario.usuarios["atendente_b"], consulta) == set()


@pytest.mark.parametrize(
    "comando",
    [
        "UPDATE atendimento SET id_loja = NULL",
        "DELETE FROM atendimento",
        "INSERT INTO atendimento (id_cliente) VALUES (gen_random_uuid())",
        "DELETE FROM mensagem",
        "UPDATE mensagem SET texto = 'x'",
    ],
)
def test_nao_ha_escrita_direta_alem_das_duas_excecoes(conn, cenario, comando):
    with como_usuario(conn, cenario.usuarios["admin"]):
        assert e_erro(tenta(conn, comando))


# ---- usuario e opcoes -----------------------------------------------------------------------


@pytest.mark.parametrize("quem", ["cliente1", "atendente_a", "admin"])
def test_usuario_so_ve_a_propria_linha(conn, cenario, quem):
    usuario = cenario.usuarios[quem]
    assert ids_visiveis(conn, usuario, "SELECT id_usuario FROM usuario") == {usuario.id}


@pytest.mark.parametrize(
    "tabela",
    ["status_atendimento", "categoria_atendimento", "canal_atendimento", "prioridade_atendimento"],
)
def test_opcoes_de_atendimento_so_para_logados(conn, cenario, tabela):
    consulta = f"SELECT 1 FROM {tabela}"
    with como_usuario(conn, cenario.usuarios["cliente1"]):
        assert len(tenta(conn, consulta)) > 0
    with como(conn, role="anon"):
        assert e_erro(tenta(conn, consulta))


# ---- mensagem -------------------------------------------------------------------------------


def test_mensagem_so_e_visivel_para_quem_ve_o_atendimento(conn, cenario, fab):
    a1 = cenario.atendimentos["a1"]
    mensagem = fab.mensagem(atendimento=a1, remetente=cenario.usuarios["cliente1"])
    consulta = "SELECT id_mensagem FROM mensagem"
    for quem, esperado in [
        ("cliente1", {mensagem}),
        ("cliente2", set()),
        ("atendente_a", {mensagem}),
        ("atendente_b", set()),
        ("admin", {mensagem}),
    ]:
        assert ids_visiveis(conn, cenario.usuarios[quem], consulta) == esperado, quem


@pytest.mark.parametrize("quem", ["cliente1", "atendente_a", "gerente_a", "admin"])
def test_pode_enviar_mensagem_em_chamado_aberto_que_ve(conn, cenario, quem):
    usuario = cenario.usuarios[quem]
    with como_usuario(conn, usuario):
        resultado = tenta(conn, INSERIR_MENSAGEM, (cenario.atendimentos["a1"], usuario.id))
    assert resultado == []


@pytest.mark.parametrize("quem", ["cliente2", "atendente_b", "operador_a", "atendente_a_inativo"])
def test_nao_envia_mensagem_em_chamado_que_nao_ve(conn, cenario, quem):
    usuario = cenario.usuarios[quem]
    with como_usuario(conn, usuario):
        resultado = tenta(conn, INSERIR_MENSAGEM, (cenario.atendimentos["a1"], usuario.id))
    assert e_erro(resultado)


def test_nao_envia_mensagem_se_nome_de_outro_usuario(conn, cenario):
    with como_usuario(conn, cenario.usuarios["cliente1"]):
        resultado = tenta(
            conn,
            INSERIR_MENSAGEM,
            (cenario.atendimentos["a1"], cenario.usuarios["cliente2"].id),
        )
    assert e_erro(resultado)


def test_nao_envia_mensagem_em_chamado_resolvido(conn, cenario):
    cliente = cenario.usuarios["cliente1"]
    with como_usuario(conn, cliente):
        resultado = tenta(conn, INSERIR_MENSAGEM, (cenario.atendimentos["resolvido"], cliente.id))
    assert e_erro(resultado)


# ---- avaliacao ------------------------------------------------------------------------------


def test_dono_avalia_chamado_resolvido_uma_unica_vez(conn, cenario):
    cliente = cenario.usuarios["cliente1"]
    resolvido = cenario.atendimentos["resolvido"]
    with como_usuario(conn, cliente):
        assert tenta(conn, INSERIR_AVALIACAO, (resolvido,)) == []
        repetida = tenta(conn, INSERIR_AVALIACAO, (resolvido,))
    assert isinstance(repetida, psycopg.errors.UniqueViolation)


def test_nao_avalia_chamado_ainda_aberto(conn, cenario):
    with como_usuario(conn, cenario.usuarios["cliente1"]):
        resultado = tenta(conn, INSERIR_AVALIACAO, (cenario.atendimentos["a1"],))
    assert e_erro(resultado)


@pytest.mark.parametrize("quem", ["cliente2", "atendente_a", "admin"])
def test_so_o_dono_avalia(conn, cenario, quem):
    with como_usuario(conn, cenario.usuarios[quem]):
        resultado = tenta(conn, INSERIR_AVALIACAO, (cenario.atendimentos["resolvido"],))
    assert e_erro(resultado)


def test_avaliacao_e_visivel_para_dono_e_equipe_da_loja(conn, cenario):
    resolvido = cenario.atendimentos["resolvido"]
    conn.execute(
        "INSERT INTO avaliacao_atendimento (id_atendimento, nota) VALUES (%s, 4)", (resolvido,)
    )
    consulta = "SELECT id_atendimento FROM avaliacao_atendimento"
    assert ids_visiveis(conn, cenario.usuarios["cliente1"], consulta) == {resolvido}
    assert ids_visiveis(conn, cenario.usuarios["atendente_a"], consulta) == {resolvido}
    assert ids_visiveis(conn, cenario.usuarios["atendente_b"], consulta) == set()
    assert ids_visiveis(conn, cenario.usuarios["cliente2"], consulta) == set()
