"""Mapeamento entre IDs numericos do Vulto e as lojas do Supabase."""

from uuid import uuid4

import pytest

from scripts.vulto_integracao.lojas import (
    CODIGO_LOJA_POR_ID_VULTO,
    resolver_id_loja_vulto,
)


@pytest.mark.parametrize(
    ("loja_id", "codigo"),
    [
        (1, "LOJA-VULTO-PINHEIROS"),
        (2, "LOJA-VULTO-SHOPPING-ELDORADO"),
        (3, "LOJA-VULTO-SAVASSI"),
        (4, "LOJA-VULTO-BATEL"),
        (5, "LOJA-VULTO-E-COMMERCE"),
        (6, "LOJA-VULTO-APP"),
        (7, "LOJA-CD-CAJAMAR"),
    ],
)
def test_resolve_id_vulto_para_uuid_da_loja(loja_id, codigo):
    id_loja = uuid4()

    assert CODIGO_LOJA_POR_ID_VULTO[loja_id] == codigo
    assert resolver_id_loja_vulto(loja_id, {codigo: id_loja}) == id_loja


def test_id_vulto_desconhecido_falha_sem_assumir_loja():
    with pytest.raises(ValueError, match="sem mapeamento"):
        resolver_id_loja_vulto(8, {})


def test_loja_ausente_no_supabase_falha_sem_usar_id_numerico():
    with pytest.raises(ValueError, match="nao existe em public.loja"):
        resolver_id_loja_vulto(4, {})


def test_id_legado_nao_inteiro_e_rejeitado():
    with pytest.raises(ValueError, match="deve ser inteiro"):
        resolver_id_loja_vulto("4", {})
