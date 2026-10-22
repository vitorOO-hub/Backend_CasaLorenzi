import pytest

from app.core.padroes import so_digitos, telefone_padrao, texto_padrao


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("  Fernanda   K. ", "fernanda k."),
        ("Casa Lorenzi Centro", "casa lorenzi centro"),
        ("São\tPaulo\n", "são paulo"),
        ("   ", None),
        ("", None),
        (None, None),
    ],
)
def test_texto_padrao(entrada, esperado):
    assert texto_padrao(entrada) == esperado


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("(11) 99999-0001", "11999990001"),
        ("+55 11 99999-0001", "11999990001"),
        ("5511999990001", "11999990001"),
        ("551140028922", "1140028922"),
        ("011 4002-8922", "1140028922"),
        ("0 11 99999-0001", "11999990001"),
        ("11999990001", "11999990001"),
        ("946232544", "946232544"),  # sem DDD: so os digitos, sem inventar o DDD
        ("sem numero", None),
        (None, None),
    ],
)
def test_telefone_padrao(entrada, esperado):
    assert telefone_padrao(entrada) == esperado


def test_so_digitos_preserva_zero_inicial():
    assert so_digitos("012.345.678-90") == "01234567890"
    assert so_digitos("abc") is None
