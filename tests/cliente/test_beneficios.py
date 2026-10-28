"""Benefícios das categorias do Lorenzi+, sem banco."""

from decimal import Decimal

import pytest

from app.cliente import beneficios
from app.cliente.repositorio import categoria_do_ano


@pytest.mark.parametrize(
    ("creditos", "categoria"),
    [
        (0, "bronze"),
        (1999, "bronze"),
        (2000, "prata"),
        (4999, "prata"),
        (5000, "ouro"),
        (9999, "ouro"),
        (10000, "black"),
        (31288, "black"),
    ],
)
def test_categoria_pelos_creditos_do_ano(creditos, categoria):
    assert categoria_do_ano(creditos) == categoria


def test_cada_categoria_tem_os_seus_beneficios():
    codigos = {
        c: [b["codigo"] for b in beneficios.beneficios(c)]
        for c in ("bronze", "prata", "ouro", "black")
    }
    assert codigos == {
        "bronze": [],
        "prata": ["frete_600"],
        "ouro": ["frete_sempre", "acesso_antecipado"],
        "black": ["frete_sempre", "acesso_antecipado", "ajuste_cortesia"],
    }
    assert all(b["titulo"] and b["descricao"] for c in codigos for b in beneficios.beneficios(c))


@pytest.mark.parametrize(
    ("categoria", "pecas", "paga_frete"),
    [
        ("bronze", "599", True),
        ("bronze", "999.99", True),
        ("bronze", "1000", False),
        ("prata", "599.99", True),
        ("prata", "600", False),
        ("ouro", "10", False),
        ("black", "10", False),
        (None, "500", True),
    ],
)
def test_frete_gratis_por_categoria(categoria, pecas, paga_frete):
    frete = beneficios.frete_com_beneficio(categoria, Decimal("49.00"), Decimal(pecas))
    assert (frete > 0) is paga_frete
