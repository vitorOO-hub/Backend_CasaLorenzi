from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.papeis import PAPEIS_COM_LOJA, Papel, UsuarioAtual


def test_valores_dos_papeis():
    assert {papel.value for papel in Papel} == {
        "atendente",
        "operador_estoque",
        "gerente_loja",
        "admin",
    }


def test_admin_nao_pertence_a_papeis_com_loja():
    assert Papel.ADMIN not in PAPEIS_COM_LOJA
    assert PAPEIS_COM_LOJA == {Papel.ATENDENTE, Papel.OPERADOR_ESTOQUE, Papel.GERENTE_LOJA}


def test_admin_acessa_qualquer_loja():
    usuario = UsuarioAtual(id_auth=uuid4(), papel=Papel.ADMIN)
    assert usuario.pode_acessar_loja(uuid4()) is True


def test_gerente_acessa_so_a_propria_loja():
    loja = uuid4()
    usuario = UsuarioAtual(id_auth=uuid4(), papel=Papel.GERENTE_LOJA, id_loja=loja)
    assert usuario.pode_acessar_loja(loja) is True
    assert usuario.pode_acessar_loja(uuid4()) is False


def test_cliente_nao_acessa_loja_nenhuma():
    usuario = UsuarioAtual(id_auth=uuid4())
    assert usuario.papel is None
    assert usuario.pode_acessar_loja(uuid4()) is False


def test_usuario_atual_e_imutavel():
    usuario = UsuarioAtual(id_auth=uuid4())
    with pytest.raises(ValidationError):
        usuario.papel = Papel.ADMIN
