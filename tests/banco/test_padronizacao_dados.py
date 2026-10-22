"""Funcoes de padrao do banco (migration 20261022180000), iguais as de app/core/padroes.py."""

import pytest

from app.core.padroes import telefone_padrao, texto_padrao

pytestmark = pytest.mark.banco

# Maiuscula acentuada depende do locale do Postgres (no Supabase, en_US.UTF-8, vira minuscula).
TEXTOS = ["  Fernanda   K. ", "Casa Lorenzi Centro", "São\tPaulo\n", "   ", "Ana  PAULA"]
TELEFONES = [
    "(11) 99999-0001",
    "+55 11 99999-0001",
    "551140028922",
    "011 4002-8922",
    "946232544",
    "sem numero",
]


@pytest.mark.parametrize("valor", TEXTOS)
def test_texto_padrao_do_banco_e_igual_ao_do_python(conn, valor):
    (banco,) = conn.execute("SELECT public.texto_padrao(%s)", (valor,)).fetchone()
    assert banco == texto_padrao(valor)


@pytest.mark.parametrize("valor", TELEFONES)
def test_telefone_padrao_do_banco_e_igual_ao_do_python(conn, valor):
    (banco,) = conn.execute("SELECT public.telefone_padrao(%s)", (valor,)).fetchone()
    assert banco == telefone_padrao(valor)


def test_nulo_continua_nulo(conn):
    assert conn.execute(
        "SELECT public.texto_padrao(NULL), public.telefone_padrao(NULL)"
    ).fetchone() == (None, None)


@pytest.mark.parametrize(
    "tabela",
    [
        "usuario",
        "loja",
        "unidade",
        "produto",
        "variacao_produto",
        "agendamento_cliente",
        "resgate_pontos",
    ],
)
def test_gatilho_de_padrao_existe_em_todas_as_tabelas_cadastrais(conn, tabela):
    existe = conn.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM pg_trigger t
            JOIN pg_class c ON c.oid = t.tgrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public'
              AND c.relname = %s
              AND t.tgname = %s
              AND NOT t.tgisinternal
        )
        """,
        (tabela, f"trg_{tabela}_normaliza_gravacao"),
    ).fetchone()[0]
    assert existe


def test_insert_e_update_normalizam_loja_e_produto(conn, fab):
    loja_id = fab.loja()
    conn.execute(
        """
        UPDATE loja
        SET nome = '  VULTO   PINHEIROS ', cidade = ' SAO   PAULO ',
            telefone = '+55 (11) 99999-0001', email = ' LOJA@EXEMPLO.COM '
        WHERE id_loja = %s
        """,
        (loja_id,),
    )
    assert conn.execute(
        "SELECT nome, cidade, telefone, email FROM loja WHERE id_loja = %s", (loja_id,)
    ).fetchone() == ("vulto pinheiros", "sao paulo", "11999990001", "loja@exemplo.com")

    produto_id = conn.execute(
        """
        INSERT INTO produto (nome, marca, preco_base, colecao)
        VALUES ('  Camisa   LINHO ', ' VULTO ', 10, 'VERAO 2026')
        RETURNING id_produto
        """
    ).fetchone()[0]
    assert conn.execute(
        "SELECT nome, marca, colecao FROM produto WHERE id_produto = %s", (produto_id,)
    ).fetchone() == ("camisa linho", "vulto", "verão 2026")
