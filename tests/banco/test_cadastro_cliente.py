"""Cadastro de cliente pelo site e endereco obrigatorio, contra um Postgres real."""

import json

import psycopg
import pytest

from tests.banco.apoio import como, tenta

pytestmark = pytest.mark.banco

DADOS = {
    "cadastro_cliente": "true",
    "nome": "  Helena Souza ",
    "telefone": "(11) 99999-0001",
    "rua": " Rua das Flores ",
    "bairro": "Centro",
    "numero_endereco": "120",
    "complemento": "Ap 4",
    "cep": "01001-000",
}


def cadastrar(conn, email="helena@exemplo.com.br", **meta):
    """O que o Supabase faz no signUp: grava em auth.users com os metadados informados."""
    dados = {**DADOS, **meta}
    return conn.execute(
        "INSERT INTO auth.users (email, raw_user_meta_data) VALUES (%s, %s::jsonb) RETURNING id",
        (email, json.dumps({k: v for k, v in dados.items() if v is not None})),
    ).fetchone()[0]


def falha(conn, **kw):
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            cadastrar(conn, **kw)


def linha(conn, auth):
    return conn.execute(
        "SELECT t.codigo, u.nome, u.email, u.telefone, u.rua, u.bairro, u.numero_endereco, "
        "u.complemento, u.cep, u.ativo, u.id_loja FROM usuario u JOIN tipo_usuario t "
        "USING (id_tipo_usuario) WHERE u.auth_user_id = %s",
        (auth,),
    ).fetchone()


# ------------------------------------------------------------------ cadastro pelo site


def test_signup_cria_o_cliente_com_endereco_normalizado(conn):
    auth = cadastrar(conn)
    assert linha(conn, auth) == (
        "cliente",
        "Helena Souza",
        "helena@exemplo.com.br",
        "11999990001",
        "Rua das Flores",
        "Centro",
        "120",
        "Ap 4",
        "01001000",
        True,
        None,
    )


def test_complemento_e_opcional(conn):
    auth = cadastrar(conn, complemento=None)
    assert linha(conn, auth)[7] is None
    auth = cadastrar(conn, email="b@x.com", complemento="   ")
    assert linha(conn, auth)[7] is None


@pytest.mark.parametrize("campo", ["nome", "telefone", "rua", "bairro", "numero_endereco", "cep"])
def test_campo_obrigatorio_ausente_barra_o_cadastro(conn, campo):
    falha(conn, **{campo: None})
    assert conn.execute("SELECT count(*) FROM usuario").fetchone()[0] == 0


@pytest.mark.parametrize(
    "meta",
    [
        {"cep": "0100100"},
        {"cep": "abcdefgh"},
        {"telefone": "12345"},
        {"nome": " "},
        {"rua": "   "},
        {"numero_endereco": ""},
        {"rua": "x" * 161},
    ],
)
def test_valores_invalidos_barram_o_cadastro(conn, meta):
    falha(conn, **meta)


def test_conta_sem_a_marca_nao_vira_cliente(conn):
    """Contas da equipe criadas pelo painel nao tem a marca (o script de vinculo cuida delas)."""
    auth = cadastrar(conn, email="equipe@casa.com", cadastro_cliente=None)
    assert linha(conn, auth) is None
    auth = cadastrar(conn, email="equipe2@casa.com", cadastro_cliente="false")
    assert linha(conn, auth) is None


@pytest.mark.parametrize(
    "malicioso",
    [
        {"papel": "admin"},
        {"tipo": "diretor"},
        {"id_loja": "00000000-0000-0000-0000-000000000001"},
        {"ativo": False},
        {"id_tipo_usuario": "1"},
    ],
)
def test_metadados_nunca_escolhem_cargo_loja_ou_status(conn, malicioso):
    auth = cadastrar(conn, email=f"m{len(malicioso)}{list(malicioso)[0]}@x.com", **malicioso)
    tipo, *_, ativo, id_loja = linha(conn, auth)
    assert (tipo, ativo, id_loja) == ("cliente", True, None)


def test_email_ja_cadastrado_barra_inclusive_o_de_funcionario_sem_login(conn, fab):
    gerente = fab.usuario("gerente_loja", loja=fab.loja())
    email = conn.execute(
        "SELECT email FROM usuario WHERE id_usuario = %s", (gerente.id,)
    ).fetchone()[0]
    with pytest.raises(psycopg.errors.UniqueViolation):
        with conn.transaction():
            cadastrar(conn, email=email)
    # A linha do funcionario continua dele.
    assert (
        conn.execute("SELECT auth_user_id FROM usuario WHERE email = %s", (email,)).fetchone()[0]
        == gerente.auth
    )


def test_email_e_guardado_em_minusculas(conn):
    auth = cadastrar(conn, email="  Maria@Exemplo.COM ")
    assert linha(conn, auth)[2] == "maria@exemplo.com"


# ------------------------------------------------------------------ regra do endereco


def inserir_usuario(conn, tipo, **colunas):
    base = {"nome": "Fulano", "email": f"{tipo}-{len(colunas)}-{id(colunas)}@x.com"}
    base.update(colunas)
    nomes = ", ".join(base)
    marcadores = ", ".join(["%s"] * len(base))
    return conn.execute(
        f"INSERT INTO usuario (id_tipo_usuario, {nomes}) VALUES "  # nosec B608
        f"((SELECT id_tipo_usuario FROM tipo_usuario WHERE codigo = %s), {marcadores}) "
        "RETURNING id_usuario",
        (tipo, *base.values()),
    ).fetchone()[0]


ENDERECO = {"rua": "Rua A", "bairro": "B", "numero_endereco": "1", "cep": "01001000"}


def test_cliente_novo_sem_endereco_completo_e_recusado(conn):
    for faltando in ENDERECO:
        parcial = {k: v for k, v in ENDERECO.items() if k != faltando}
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                inserir_usuario(conn, "cliente", **parcial)
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            inserir_usuario(conn, "cliente")
    inserir_usuario(conn, "cliente", **ENDERECO)


def test_equipe_nao_tem_endereco(conn):
    for coluna in ("rua", "bairro", "numero_endereco", "complemento", "cep"):
        valor = "01001000" if coluna == "cep" else "x"
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                inserir_usuario(conn, "atendente", **{coluna: valor})


def test_cliente_completo_nao_volta_a_ficar_incompleto(conn):
    id_usuario = inserir_usuario(conn, "cliente", **ENDERECO)
    for coluna in ENDERECO:
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute(
                    f"UPDATE usuario SET {coluna} = NULL WHERE id_usuario = %s", (id_usuario,)
                )  # nosec B608
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute(
                    f"UPDATE usuario SET {coluna} = '  ' WHERE id_usuario = %s", (id_usuario,)
                )  # nosec B608
    conn.execute("UPDATE usuario SET rua = 'Rua B' WHERE id_usuario = %s", (id_usuario,))


def test_cliente_antigo_sem_endereco_continua_editavel(conn):
    """Linhas anteriores a regra (sem endereco) seguem funcionando ate mexerem no endereco."""
    id_usuario = inserir_usuario(conn, "cliente", **ENDERECO)
    conn.execute("ALTER TABLE usuario DISABLE TRIGGER trg_usuario_validar_endereco")
    conn.execute(
        "UPDATE usuario SET rua = NULL, bairro = NULL, numero_endereco = NULL, cep = NULL "
        "WHERE id_usuario = %s",
        (id_usuario,),
    )
    conn.execute("ALTER TABLE usuario ENABLE TRIGGER trg_usuario_validar_endereco")
    conn.execute("UPDATE usuario SET telefone = '11988887777' WHERE id_usuario = %s", (id_usuario,))
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            conn.execute("UPDATE usuario SET rua = 'Rua Nova' WHERE id_usuario = %s", (id_usuario,))


def test_nao_vira_equipe_levando_o_endereco(conn):
    id_usuario = inserir_usuario(conn, "cliente", **ENDERECO)
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            conn.execute(
                "UPDATE usuario SET id_tipo_usuario = (SELECT id_tipo_usuario FROM tipo_usuario "
                "WHERE codigo = 'atendente') WHERE id_usuario = %s",
                (id_usuario,),
            )


@pytest.mark.parametrize("cep", ["1234567", "123456789", "01.001-000", "abcdefgh", ""])
def test_cep_precisa_ter_8_digitos(conn, cep):
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            inserir_usuario(conn, "cliente", **{**ENDERECO, "cep": cep})


# ------------------------------------------------------------------ cada cliente, a propria sessao


def test_cada_cliente_so_le_a_propria_linha_com_o_proprio_endereco(conn):
    ana = cadastrar(conn, email="ana@x.com", nome="Ana Souza", rua="Rua da Ana")
    bia = cadastrar(conn, email="bia@x.com", nome="Bia Lima", rua="Rua da Bia")
    consulta = "SELECT nome, rua, cep FROM usuario"
    with como(conn, sub=ana):
        assert tenta(conn, consulta) == [("Ana Souza", "Rua da Ana", "01001000")]
    with como(conn, sub=bia):
        assert tenta(conn, consulta) == [("Bia Lima", "Rua da Bia", "01001000")]
    with como(conn, role="anon"):
        assert isinstance(tenta(conn, consulta), psycopg.errors.InsufficientPrivilege)


def test_cliente_logado_nao_escreve_na_propria_linha_pelo_front(conn):
    ana = cadastrar(conn, email="ana2@x.com")
    with como(conn, sub=ana):
        for comando in (
            "UPDATE usuario SET id_tipo_usuario = (SELECT id_tipo_usuario FROM tipo_usuario "
            "WHERE codigo = 'diretor')",
            "UPDATE usuario SET rua = 'Outra'",
            "DELETE FROM usuario",
        ):
            assert isinstance(tenta(conn, comando), psycopg.errors.InsufficientPrivilege), comando


def test_cliente_novo_nao_tem_cargo_no_token(conn):
    """O hook so da cargo a quem e da equipe: cliente fica sem `papel` e sem loja."""
    auth = cadastrar(conn, email="ana3@x.com")
    resultado = conn.execute(
        "SELECT public.hook_claims_token(%s::jsonb)",
        (json.dumps({"user_id": str(auth), "claims": {"sub": str(auth)}}),),
    ).fetchone()[0]
    assert "papel" not in resultado["claims"] and "loja_id" not in resultado["claims"]
