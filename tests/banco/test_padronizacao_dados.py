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
