"""Regras da area de chamados: escopo, quem pode o que e as transicoes de estado.

Toda escrita roda numa transacao com o chamado travado (`FOR UPDATE`), entao duas pessoas
assumindo o mesmo chamado ao mesmo tempo resultam em um sucesso e um 409.
"""

from typing import Any
from uuid import UUID

from sqlalchemy.engine import Connection

from app.chamados import repositorio
from app.chamados.erros import (
    CadastroInativo,
    ChamadoFinalizado,
    ChamadoJaAssumido,
    ChamadoNaoEncontrado,
    ChamadoSemResponsavel,
    SemPermissaoNoChamado,
)
from app.chamados.repositorio import FINAIS, Escopo
from app.core.erros_auth import SemPermissao
from app.core.papeis import Papel, UsuarioAtual

PAPEIS_DO_PAINEL = (Papel.ATENDENTE, Papel.GERENTE_LOJA, Papel.ADMIN)
# Gerente e admin enxergam compras do cliente e podem agir em chamado de outra pessoa.
GESTAO = (Papel.GERENTE_LOJA, Papel.ADMIN)


def resolver_loja(usuario: UsuarioAtual, id_loja_pedida: UUID | None) -> UUID | None:
    """Atendente e gerente so a propria loja (a do token); admin, a rede ou uma loja."""
    if usuario.papel is Papel.ADMIN:
        return id_loja_pedida
    if usuario.id_loja is None:
        raise SemPermissao()
    if id_loja_pedida is not None and id_loja_pedida != usuario.id_loja:
        raise SemPermissao()
    return usuario.id_loja


def montar_escopo(
    conexao: Connection, usuario: UsuarioAtual, id_loja_pedida: UUID | None
) -> Escopo:
    """Escopo da requisicao. Falha cedo (403) se a conta nao tem cadastro ativo."""
    id_loja = resolver_loja(usuario, id_loja_pedida)
    id_usuario = repositorio.id_usuario_ativo(conexao, usuario.id_auth)
    if id_usuario is None:
        raise CadastroInativo()
    # A equipe de uma loja tambem atende os chamados sem loja (fila geral). Admin que filtra
    # uma loja especifica ve so ela.
    incluir_sem_loja = usuario.papel is not Papel.ADMIN
    return Escopo(id_usuario=id_usuario, id_loja=id_loja, incluir_sem_loja=incluir_sem_loja)


def opcoes(conexao: Connection, usuario: UsuarioAtual, escopo: Escopo) -> dict[str, Any]:
    return repositorio.opcoes(conexao, escopo, todas_as_lojas=usuario.papel is Papel.ADMIN)


def resumo(conexao: Connection, escopo: Escopo) -> dict[str, Any]:
    return repositorio.resumo(conexao, escopo)


def listar(conexao: Connection, escopo: Escopo, **filtros: Any) -> dict[str, Any]:
    total, itens = repositorio.listar(conexao, escopo, **filtros)
    return {"total": total, "itens": itens}


def detalhe(
    conexao: Connection, usuario: UsuarioAtual, escopo: Escopo, id_atendimento: UUID
) -> dict[str, Any]:
    achado = repositorio.obter_detalhe(
        conexao, escopo, id_atendimento, ver_compras=usuario.papel in GESTAO
    )
    if achado is None:
        raise ChamadoNaoEncontrado()
    return achado


def mensagens(conexao: Connection, escopo: Escopo, id_atendimento: UUID) -> list[dict[str, Any]]:
    if repositorio.obter_item(conexao, escopo, id_atendimento) is None:
        raise ChamadoNaoEncontrado()
    return repositorio.mensagens(conexao, id_atendimento)


def _travar_aberto(conexao: Connection, escopo: Escopo, id_atendimento: UUID) -> dict[str, Any]:
    trava = repositorio.travar(conexao, escopo, id_atendimento)
    if trava is None:
        raise ChamadoNaoEncontrado()
    if trava["status_codigo"] in FINAIS:
        raise ChamadoFinalizado()
    return trava


def enviar_mensagem(
    conexao: Connection,
    usuario: UsuarioAtual,
    escopo: Escopo,
    id_atendimento: UUID,
    texto: str,
) -> dict[str, Any]:
    """Resposta da equipe. Sem responsavel, quem responde assume; com responsavel, so ele
    (ou a gestao) pode responder."""
    trava = _travar_aberto(conexao, escopo, id_atendimento)
    responsavel = trava["id_usuario_responsavel"]
    if responsavel not in (None, escopo.id_usuario) and usuario.papel not in GESTAO:
        raise ChamadoJaAssumido(trava["responsavel_nome"])
    id_mensagem = repositorio.gravar_mensagem(conexao, id_atendimento, escopo.id_usuario, texto)
    repositorio.registrar_resposta(conexao, id_atendimento, escopo.id_usuario)
    conexao.commit()
    criada = next(
        m for m in repositorio.mensagens(conexao, id_atendimento) if m["id_mensagem"] == id_mensagem
    )
    return criada


def assumir(conexao: Connection, escopo: Escopo, id_atendimento: UUID) -> dict[str, Any]:
    trava = _travar_aberto(conexao, escopo, id_atendimento)
    responsavel = trava["id_usuario_responsavel"]
    if responsavel is not None:
        raise ChamadoJaAssumido(trava["responsavel_nome"], voce=responsavel == escopo.id_usuario)
    repositorio.assumir(conexao, id_atendimento, escopo.id_usuario)
    conexao.commit()
    return repositorio.obter_item(conexao, escopo, id_atendimento)  # type: ignore[return-value]


def resolver(
    conexao: Connection, usuario: UsuarioAtual, escopo: Escopo, id_atendimento: UUID
) -> dict[str, Any]:
    trava = _travar_aberto(conexao, escopo, id_atendimento)
    responsavel = trava["id_usuario_responsavel"]
    if usuario.papel not in GESTAO:
        if responsavel is None:
            raise ChamadoSemResponsavel()
        if responsavel != escopo.id_usuario:
            raise SemPermissaoNoChamado()
    repositorio.resolver(conexao, id_atendimento)
    conexao.commit()
    return repositorio.obter_item(conexao, escopo, id_atendimento)  # type: ignore[return-value]
