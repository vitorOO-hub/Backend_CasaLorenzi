"""RLS da tabela chamado_anexo: so enxerga quem enxerga o chamado, e ninguem escreve direto."""

import pytest

from tests.banco.apoio import como, e_erro, tenta
from tests.banco.fabrica import Usuario

pytestmark = pytest.mark.banco


def como_usuario(conn, usuario: Usuario):
    papel = {"diretor": "admin"}.get(usuario.tipo, usuario.tipo)
    papel = None if papel == "cliente" else papel
    loja = None if papel in (None, "admin") else usuario.loja
    return como(conn, sub=usuario.auth, papel=papel, loja=loja)


@pytest.fixture
def cenario(conn, fab):
    loja_a, loja_b = fab.loja(), fab.loja()
    cliente, outro = fab.usuario("cliente"), fab.usuario("cliente")
    atendimento = fab.atendimento(cliente=cliente, loja=loja_a)
    anexo = conn.execute(
        "INSERT INTO chamado_anexo (id_atendimento, nome, caminho) "
        "VALUES (%s, 'foto.jpg', 'x/foto.jpg') "
        "RETURNING id_anexo",
        (atendimento,),
    ).fetchone()[0]
    return {
        "anexo": anexo,
        "cliente": cliente,
        "outro": outro,
        "ate_a": fab.usuario("atendente", loja=loja_a),
        "ate_b": fab.usuario("atendente", loja=loja_b),
        "admin": fab.usuario("diretor"),
    }


@pytest.mark.parametrize(
    ("quem", "ve"),
    [("cliente", True), ("outro", False), ("ate_a", True), ("ate_b", False), ("admin", True)],
)
def test_leitura_segue_a_visibilidade_do_chamado(conn, cenario, quem, ve):
    with como_usuario(conn, cenario[quem]):
        linhas = tenta(conn, "SELECT id_anexo FROM chamado_anexo")
    assert (len(linhas) == 1) is ve


def test_anon_nao_le(conn, cenario):
    with como(conn, role="anon"):
        assert e_erro(tenta(conn, "SELECT 1 FROM chamado_anexo"))


@pytest.mark.parametrize(
    "comando",
    [
        "INSERT INTO chamado_anexo (id_atendimento, nome, caminho) "
        "VALUES (gen_random_uuid(), 'a', 'b')",
        "UPDATE chamado_anexo SET nome = 'x'",
        "DELETE FROM chamado_anexo",
    ],
)
def test_ninguem_escreve_direto(conn, cenario, comando):
    with como_usuario(conn, cenario["admin"]):
        assert e_erro(tenta(conn, comando))
