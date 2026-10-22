"""Vulto+ do cliente na ficha do painel: mesma regra de acesso da ficha e valor dos resgates so para
gerente e admin. Contra um Postgres real."""

from decimal import Decimal

import pytest

from app.chamados import service as chamados
from app.clientes import service
from app.clientes.erros import ClienteNaoEncontrado
from app.core.papeis import Papel, UsuarioAtual

pytestmark = pytest.mark.banco


def como(usuario) -> UsuarioAtual:
    papel = {"diretor": Papel.ADMIN}.get(usuario.tipo) or Papel(usuario.tipo)
    return UsuarioAtual(
        id_auth=usuario.auth, papel=papel, id_loja=None if papel is Papel.ADMIN else usuario.loja
    )


def ver(conexao, usuario, id_cliente):
    token = como(usuario)
    escopo = chamados.montar_escopo(conexao, token, None)
    return service.vulto_mais(conexao, token, escopo, id_cliente)


@pytest.fixture
def cena(fab_sa):
    c = fab_sa.conn
    loja_a, loja_b = fab_sa.loja(), fab_sa.loja()
    cliente = fab_sa.usuario("cliente")
    c.execute("UPDATE usuario SET id_loja = %s WHERE id_usuario = %s", (loja_a, cliente.id))
    fab_sa.atendimento(cliente=cliente, loja=loja_a)  # cliente visivel para a equipe da loja A
    for tipo, pontos in (("credito", 2500), ("resgate", -500)):
        c.execute(
            "INSERT INTO movimento_pontos (id_usuario, tipo, pontos, ocorrido_em, descricao) "
            "VALUES (%s, %s, %s, now(), 'teste')",
            (cliente.id, tipo, pontos),
        )
    c.execute(
        "INSERT INTO resgate_pontos (id_usuario, resgatado_em, pontos, desconto, id_loja, "
        "atendente) VALUES (%s, now(), 500, 25, %s, 'Camila Duarte')",
        (cliente.id, loja_a),
    )
    return {
        "cliente": cliente,
        "loja_a": loja_a,
        "atendente_a": fab_sa.usuario("atendente", loja=loja_a),
        "gerente_a": fab_sa.usuario("gerente_loja", loja=loja_a),
        "atendente_b": fab_sa.usuario("atendente", loja=loja_b),
        "admin": fab_sa.usuario("diretor"),
    }


def test_gerente_ve_saldo_categoria_extrato_resgates_com_valor(sa_conn, cena):
    r = ver(sa_conn, cena["gerente_a"], cena["cliente"].id)
    assert (r["saldo"], r["categoria"], r["proxima_categoria"]) == (2000, "prata", "ouro")
    assert len(r["extrato"]) == 2 and r["loja_cadastro"]
    assert r["resgates"][0]["pontos"] == 500 and r["resgates"][0]["desconto"] == Decimal("25")
    assert r["resgates"][0]["atendente"] == "camila duarte"  # padronizado no banco


def test_atendente_ve_os_pontos_sem_o_valor_dos_resgates(sa_conn, cena):
    r = ver(sa_conn, cena["atendente_a"], cena["cliente"].id)
    assert r["saldo"] == 2000 and r["resgates"][0]["desconto"] is None


def test_quem_nao_ve_o_cliente_nao_ve_os_pontos(sa_conn, cena):
    with pytest.raises(ClienteNaoEncontrado):
        ver(sa_conn, cena["atendente_b"], cena["cliente"].id)


def test_admin_ve_qualquer_cliente(sa_conn, cena):
    assert ver(sa_conn, cena["admin"], cena["cliente"].id)["saldo"] == 2000
