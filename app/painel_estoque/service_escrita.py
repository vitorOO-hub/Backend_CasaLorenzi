"""Regras de escrita do estoque do painel: movimentacoes e ajustes de inventario.

Quem faz a operacao e sempre a pessoa do token (nunca vem do corpo). Operador e gerente so mexem
na propria loja; o admin informa a loja. O saldo nunca fica negativo e duas operacoes ao mesmo
tempo se enfileiram na trava da linha do estoque.
"""

from typing import Any
from uuid import UUID

from sqlalchemy.engine import Connection

from app.chamados.repositorio import id_usuario_ativo
from app.core.erros_auth import SemPermissao
from app.core.papeis import Papel, UsuarioAtual
from app.gestao import auditoria
from app.painel_estoque import repositorio_escrita, service
from app.painel_estoque.erros import (
    AjusteJaDecidido,
    AjusteNaoEncontrado,
    LojaObrigatoria,
    PecaNaoEncontrada,
    SaldoInsuficiente,
    SemDiferenca,
)
from app.painel_estoque.repositorio import FiltroMovimentacoes

PAPEIS_DA_GESTAO = (Papel.GERENTE_LOJA, Papel.ADMIN)


def _quem_e_onde(
    conexao: Connection, usuario: UsuarioAtual, id_loja_pedida: UUID | None
) -> tuple[UUID, UUID]:
    """(id do usuario no banco, loja da operacao). Sem cadastro ativo ou sem loja, nao opera."""
    loja = service.loja_do_escopo(usuario, id_loja_pedida)
    id_usuario = id_usuario_ativo(conexao, usuario.id_auth)
    if id_usuario is None:
        raise SemPermissao()
    if loja is None:
        raise LojaObrigatoria()
    return id_usuario, loja


def _saldo_travado(conexao: Connection, id_loja: UUID, id_variacao: UUID, *, criar: bool) -> int:
    saldo = repositorio_escrita.travar_estoque(conexao, id_loja, id_variacao)
    if saldo is None and criar:
        repositorio_escrita.criar_linha_de_estoque(conexao, id_loja, id_variacao)
        saldo = repositorio_escrita.travar_estoque(conexao, id_loja, id_variacao)
    return saldo or 0


def _movimentacao(conexao: Connection, id_movimentacao: UUID) -> dict[str, Any]:
    filtro = FiltroMovimentacoes(id_movimentacao=id_movimentacao)
    return service.montar_movimentacoes(conexao, filtro, limit=1, offset=0)["itens"][0]


def _ajuste(conexao: Connection, id_ajuste: UUID) -> dict[str, Any]:
    return repositorio_escrita.ajustes(
        conexao,
        id_loja=None,
        id_solicitante=None,
        status=None,
        id_ajuste=id_ajuste,
        limit=1,
        offset=0,
    )[2][0]


def registrar_movimentacao(
    conexao: Connection,
    usuario: UsuarioAtual,
    *,
    id_loja: UUID | None,
    sku: str,
    tipo: str,
    quantidade: int,
    motivo: str,
) -> dict[str, Any]:
    """Entrada ou saida avulsa. Devolve a linha ja gravada, como o historico a mostra."""
    id_usuario, loja = _quem_e_onde(conexao, usuario, id_loja)
    id_variacao = repositorio_escrita.achar_peca(conexao, sku)
    if id_variacao is None:
        raise PecaNaoEncontrada()
    entrada = tipo == "entrada"
    saldo = _saldo_travado(conexao, loja, id_variacao, criar=entrada)
    novo = saldo + quantidade if entrada else saldo - quantidade
    if novo < 0:
        raise SaldoInsuficiente(saldo)
    id_movimentacao = repositorio_escrita.gravar_movimentacao(
        conexao,
        id_loja=loja,
        id_variacao=id_variacao,
        id_usuario=id_usuario,
        tipo=tipo,
        quantidade=quantidade,
        anterior=saldo,
        posterior=novo,
        motivo=motivo,
    )
    conexao.commit()
    return _movimentacao(conexao, id_movimentacao)


def solicitar_ajuste(
    conexao: Connection,
    usuario: UsuarioAtual,
    *,
    id_loja: UUID | None,
    sku: str,
    quantidade_contada: int,
    motivo: str,
) -> dict[str, Any]:
    """Pedido de ajuste de inventario: o saldo so muda quando a gestao aprova."""
    id_usuario, loja = _quem_e_onde(conexao, usuario, id_loja)
    id_variacao = repositorio_escrita.achar_peca(conexao, sku)
    if id_variacao is None:
        raise PecaNaoEncontrada()
    saldo = repositorio_escrita.travar_estoque(conexao, loja, id_variacao) or 0
    diferenca = quantidade_contada - saldo
    if diferenca == 0:
        raise SemDiferenca()
    id_ajuste = repositorio_escrita.criar_ajuste(
        conexao,
        id_loja=loja,
        id_variacao=id_variacao,
        id_solicitante=id_usuario,
        quantidade=diferenca,
        motivo=motivo,
    )
    conexao.commit()
    return _ajuste(conexao, id_ajuste)


def listar_ajustes(
    conexao: Connection,
    usuario: UsuarioAtual,
    *,
    id_loja: UUID | None,
    status: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    """Gestao ve os ajustes da loja; o operador ve so os que ele mesmo pediu."""
    loja = service.loja_do_escopo(usuario, id_loja)
    id_solicitante = None
    if service.somente_minhas(usuario):
        id_solicitante = id_usuario_ativo(conexao, usuario.id_auth)
        if id_solicitante is None:
            raise SemPermissao()
    total, pendentes, itens = repositorio_escrita.ajustes(
        conexao,
        id_loja=loja,
        id_solicitante=id_solicitante,
        status=status,
        limit=limit,
        offset=offset,
    )
    return {"total": total, "pendentes": pendentes, "itens": itens}


def _ajuste_pendente(
    conexao: Connection, usuario: UsuarioAtual, id_ajuste: UUID
) -> tuple[UUID, dict[str, Any]]:
    if usuario.papel not in PAPEIS_DA_GESTAO:
        raise SemPermissao()
    id_decisor = id_usuario_ativo(conexao, usuario.id_auth)
    if id_decisor is None:
        raise SemPermissao()
    travado = repositorio_escrita.travar_ajuste(
        conexao, id_ajuste, service.loja_do_escopo(usuario, None)
    )
    if travado is None:
        raise AjusteNaoEncontrado()
    if travado["status"] != "pendente":
        raise AjusteJaDecidido()
    return id_decisor, travado


def aprovar_ajuste(conexao: Connection, usuario: UsuarioAtual, id_ajuste: UUID) -> dict[str, Any]:
    """Aplica a diferenca ao saldo de agora (pode ter mudado desde o pedido) e fecha o ajuste."""
    id_decisor, ajuste = _ajuste_pendente(conexao, usuario, id_ajuste)
    loja, variacao, diferenca = ajuste["id_loja"], ajuste["id_variacao"], ajuste["quantidade"]
    saldo = _saldo_travado(conexao, loja, variacao, criar=diferenca > 0)
    novo = saldo + diferenca
    if novo < 0:
        raise SaldoInsuficiente(saldo)
    repositorio_escrita.gravar_movimentacao(
        conexao,
        id_loja=loja,
        id_variacao=variacao,
        # A contagem foi de quem pediu; a decisao fica registrada no proprio ajuste.
        id_usuario=ajuste["id_usuario_solicitante"],
        tipo="ajuste_positivo" if diferenca > 0 else "ajuste_negativo",
        quantidade=abs(diferenca),
        anterior=saldo,
        posterior=novo,
        motivo=f"Ajuste aprovado: {ajuste['motivo']}"[:500],
    )
    repositorio_escrita.decidir_ajuste(
        conexao, id_ajuste, status="aprovado", id_decisor=id_decisor, motivo_recusa=None
    )
    auditoria.registrar(
        conexao,
        usuario,
        "Aprovou ajuste manual",
        f"{auditoria.sku_da_variacao(conexao, variacao)} · {diferenca} un.",
    )
    conexao.commit()
    return _ajuste(conexao, id_ajuste)


def recusar_ajuste(
    conexao: Connection, usuario: UsuarioAtual, id_ajuste: UUID, motivo: str
) -> dict[str, Any]:
    id_decisor, ajuste = _ajuste_pendente(conexao, usuario, id_ajuste)
    repositorio_escrita.decidir_ajuste(
        conexao, id_ajuste, status="rejeitado", id_decisor=id_decisor, motivo_recusa=motivo
    )
    auditoria.registrar(
        conexao,
        usuario,
        "Recusou ajuste manual",
        f"{auditoria.sku_da_variacao(conexao, ajuste['id_variacao'])} · "
        f"{ajuste['quantidade']} un. · {motivo}",
    )
    conexao.commit()
    return _ajuste(conexao, id_ajuste)
