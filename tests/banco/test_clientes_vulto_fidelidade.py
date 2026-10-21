"""Clientes importados do Vulto+ (sem endereco, e-mail opcional), cadastro que assume a conta
importada e extrato de pontos, contra um Postgres real."""

import json

import psycopg
import pytest

pytestmark = pytest.mark.banco

CPF = "52998224725"

DADOS = {
    "cadastro_cliente": "true",
    "nome": "Helena Souza",
    "telefone": "(11) 99999-0001",
    "rua": "Rua das Flores",
    "bairro": "Centro",
    "numero_endereco": "120",
    "cep": "01001-000",
}


def importar(conn, *, documento=CPF, email="helena@exemplo.com.br", loja=None):
    """O que a carga do Vulto+ grava: cliente sem endereco e sem login."""
    return conn.execute(
        "INSERT INTO usuario (id_tipo_usuario, documento, nome, email, id_loja, origem_cadastro, "
        "aceita_mensagem, observacao) VALUES ((SELECT id_tipo_usuario FROM tipo_usuario "
        "WHERE codigo = 'cliente'), %s, 'cliente vulto+ (nome a confirmar)', %s, %s, 'vulto+', "
        "true, 'nome não informado: pedir ao cliente') RETURNING id_usuario",
        (documento, email, loja),
    ).fetchone()[0]


def cadastrar(conn, email="helena@exemplo.com.br", **meta):
    dados = {**DADOS, **meta}
    return conn.execute(
        "INSERT INTO auth.users (email, raw_user_meta_data) VALUES (%s, %s::jsonb) RETURNING id",
        (email, json.dumps({k: v for k, v in dados.items() if v is not None})),
    ).fetchone()[0]


def falha(conn, erro, comando, parametros=()):
    with pytest.raises(erro):
        with conn.transaction():
            conn.execute(comando, parametros)


# ------------------------------------------------------------------ importacao


def test_cliente_importado_entra_sem_endereco_e_sem_email(conn, fab):
    loja = fab.loja()
    importar(conn, loja=loja)
    importar(conn, documento="11144477735", email=None)
    assert (
        conn.execute(
            "SELECT count(*) FROM usuario WHERE origem_cadastro = 'vulto+' AND rua IS NULL"
        ).fetchone()[0]
        == 2
    )


def test_cliente_que_nao_e_importado_continua_precisando_de_endereco(conn):
    falha(
        conn,
        psycopg.errors.CheckViolation,
        "INSERT INTO usuario (id_tipo_usuario, nome, email) VALUES ((SELECT id_tipo_usuario "
        "FROM tipo_usuario WHERE codigo = 'cliente'), 'Ana', 'ana@x.com')",
    )


def test_equipe_continua_precisando_de_email(conn):
    falha(
        conn,
        psycopg.errors.CheckViolation,
        "INSERT INTO usuario (id_tipo_usuario, nome) VALUES ((SELECT id_tipo_usuario "
        "FROM tipo_usuario WHERE codigo = 'atendente'), 'Bia')",
    )


def test_origem_desconhecida_e_recusada(conn):
    falha(
        conn,
        psycopg.errors.CheckViolation,
        "UPDATE usuario SET origem_cadastro = 'outra' WHERE id_usuario = %s",
        (importar(conn),),
    )


def test_importado_que_edita_o_endereco_precisa_dele_completo(conn):
    id_usuario = importar(conn)
    falha(
        conn,
        psycopg.errors.CheckViolation,
        "UPDATE usuario SET rua = 'Rua A' WHERE id_usuario = %s",
        (id_usuario,),
    )
    conn.execute(
        "UPDATE usuario SET observacao = 'ligar à tarde' WHERE id_usuario = %s", (id_usuario,)
    )


# ------------------------------------------------------------------ cadastro pelo site


def test_cadastro_com_mesmo_cpf_e_email_assume_a_conta_importada(conn):
    id_usuario = importar(conn)
    auth = cadastrar(conn, documento="529.982.247-25")
    linha = conn.execute(
        "SELECT id_usuario, nome, telefone, cep, origem_cadastro, aceita_mensagem FROM usuario "
        "WHERE auth_user_id = %s",
        (auth,),
    ).fetchone()
    assert linha == (id_usuario, "Helena Souza", "11999990001", "01001000", "vulto+", True)
    assert conn.execute("SELECT count(*) FROM usuario").fetchone()[0] == 1


def test_cpf_importado_com_outro_email_barra_o_cadastro(conn):
    importar(conn)
    with pytest.raises(psycopg.errors.UniqueViolation, match="CPF ja cadastrado"):
        with conn.transaction():
            cadastrar(conn, email="outra@exemplo.com", documento=CPF)
    assert conn.execute("SELECT auth_user_id FROM usuario").fetchone()[0] is None


def test_conta_importada_ja_ligada_nao_e_assumida_de_novo(conn):
    importar(conn)
    cadastrar(conn, documento=CPF)
    with pytest.raises(psycopg.errors.UniqueViolation):
        with conn.transaction():
            cadastrar(conn, email="helena@exemplo.com.br", documento=CPF)


def test_cadastro_novo_guarda_o_cpf(conn):
    auth = cadastrar(conn, documento="111.444.777-35")
    assert conn.execute(
        "SELECT documento, origem_cadastro FROM usuario WHERE auth_user_id = %s", (auth,)
    ).fetchone() == ("11144477735", None)


def test_cpf_com_tamanho_errado_barra_o_cadastro(conn):
    with pytest.raises(psycopg.errors.CheckViolation, match="CPF invalido"):
        with conn.transaction():
            cadastrar(conn, documento="123")


# ------------------------------------------------------------------ extrato e resgates


def test_extrato_aceita_credito_com_validade_e_soma_o_saldo(conn, fab):
    id_usuario = importar(conn)
    for tipo, pontos, vence in (
        ("credito", 500, "2027-01-01"),
        ("resgate", -200, None),
        ("vencimento", -100, None),
        ("ajuste", 50, None),
    ):
        conn.execute(
            "INSERT INTO movimento_pontos (id_usuario, tipo, pontos, ocorrido_em, vence_em, "
            "descricao, origem) VALUES (%s, %s, %s, now(), %s, 'teste', 'vulto+')",
            (id_usuario, tipo, pontos, vence),
        )
    assert (
        conn.execute(
            "SELECT sum(pontos) FROM movimento_pontos WHERE id_usuario = %s", (id_usuario,)
        ).fetchone()[0]
        == 250
    )
    conn.execute(
        "INSERT INTO resgate_pontos (id_usuario, resgatado_em, pontos, desconto, id_loja, "
        "atendente) VALUES (%s, now(), 1000, 50, %s, 'camila duarte')",
        (id_usuario, fab.loja()),
    )


@pytest.mark.parametrize(
    "tipo,pontos,vence",
    [
        ("credito", -10, None),
        ("resgate", 10, None),
        ("vencimento", 10, None),
        ("ajuste", 0, None),
        ("resgate", -10, "2027-01-01"),
        ("bonus", 10, None),
    ],
)
def test_extrato_recusa_sinal_ou_tipo_errado(conn, tipo, pontos, vence):
    falha(
        conn,
        psycopg.errors.CheckViolation,
        "INSERT INTO movimento_pontos (id_usuario, tipo, pontos, ocorrido_em, vence_em, descricao) "
        "VALUES (%s, %s, %s, now(), %s, 'teste')",
        (importar(conn), tipo, pontos, vence),
    )


def test_cliente_nao_le_extrato_nem_resgates_direto(conn):
    from tests.banco.apoio import como, e_erro, tenta

    with como(conn, role="authenticated", sub="00000000-0000-0000-0000-000000000001"):
        for tabela in ("movimento_pontos", "resgate_pontos"):
            resultado = tenta(conn, f"SELECT * FROM {tabela}")  # noqa: S608
            assert e_erro(resultado) or resultado == []
