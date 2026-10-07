"""Regras do chat ao vivo: escopo, quem pode responder e o cursor de recuperacao de mensagens."""

from typing import Any
from uuid import UUID

from sqlalchemy.engine import Connection

from app.chamados import repositorio as repo_chamados
from app.chamados import service as chamados
from app.chamados.erros import ChamadoNaoEncontrado
from app.chamados.repositorio import FINAIS, Escopo
from app.chamados.service import GESTAO, PAPEIS_DO_PAINEL, montar_escopo
from app.chat import repositorio
from app.chat.erros import MensagemDeReferenciaInexistente
from app.core.papeis import UsuarioAtual

__all__ = ["PAPEIS_DO_PAINEL", "montar_escopo"]

PREFIXO_DO_CANAL = "chamado"


def topico_do_canal(id_atendimento: UUID) -> str:
    """Nome do canal privado do Realtime; as policies de `realtime.messages` casam com ele."""
    return f"{PREFIXO_DO_CANAL}:{id_atendimento}"


def _no_escopo(conexao: Connection, escopo: Escopo, id_atendimento: UUID) -> dict[str, Any]:
    item = repo_chamados.obter_item(conexao, escopo, id_atendimento)
    if item is None:
        raise ChamadoNaoEncontrado()
    return item


def listar(conexao: Connection, escopo: Escopo, **filtros: Any) -> dict[str, Any]:
    total, itens = repositorio.listar(conexao, escopo, **filtros)
    return {"total": total, "itens": itens}


def resumo(conexao: Connection, escopo: Escopo) -> dict[str, int]:
    return repositorio.resumo(conexao, escopo)


def regra_de_resposta(
    status_codigo: str,
    id_responsavel: UUID | None,
    nome_responsavel: str | None,
    id_usuario: UUID,
    usuario: UsuarioAtual,
) -> tuple[bool, str | None]:
    """Quem pode escrever na conversa (a mesma regra do POST que grava a mensagem)."""
    if status_codigo in FINAIS:
        return False, "Este chamado foi encerrado."
    if id_responsavel not in (None, id_usuario) and usuario.papel not in GESTAO:
        return (
            False,
            f"Este chamado esta com {nome_responsavel}. So ele ou a gestao pode responder.",
        )
    return True, None


def sessao(
    conexao: Connection, usuario: UsuarioAtual, escopo: Escopo, id_atendimento: UUID
) -> dict[str, Any]:
    item = _no_escopo(conexao, escopo, id_atendimento)
    extra = repositorio.dados_da_sessao(conexao, escopo, id_atendimento)
    pode, motivo = regra_de_resposta(
        item["status"]["codigo"],
        item["id_usuario_responsavel"],
        item["responsavel_nome"],
        escopo.id_usuario,
        usuario,
    )
    return {
        "id_atendimento": id_atendimento,
        "topico": topico_do_canal(id_atendimento),
        "canal_privado": True,
        "filtro_mensagens": f"id_atendimento=eq.{id_atendimento}",
        "eu": {
            "id_usuario": escopo.id_usuario,
            "nome": extra["meu_nome"],
            "papel": usuario.papel.value if usuario.papel else "",
        },
        "status": item["status"],
        "id_usuario_responsavel": item["id_usuario_responsavel"],
        "responsavel_nome": item["responsavel_nome"],
        "sou_responsavel": item["sou_responsavel"],
        "pode_responder": pode,
        "motivo_bloqueio": motivo,
        "ultimo_id_mensagem": extra["ultimo_id_mensagem"],
        "nao_lidas": int(extra["nao_lidas"]),
    }


def mensagens(
    conexao: Connection,
    escopo: Escopo,
    id_atendimento: UUID,
    *,
    apos: UUID | None,
    limit: int,
) -> dict[str, Any]:
    """Sem `apos`: as ultimas `limit`. Com `apos`: so o que veio depois dessa mensagem."""
    _no_escopo(conexao, escopo, id_atendimento)
    if apos is None:
        lista = repositorio.ultimas_mensagens(conexao, id_atendimento, limit)
    else:
        referencia = repositorio.referencia_da_mensagem(conexao, id_atendimento, apos)
        if referencia is None:
            raise MensagemDeReferenciaInexistente()
        lista = repositorio.mensagens_apos(conexao, id_atendimento, referencia, limit)
    # Cursor: a ultima do lote; se o lote veio vazio, o cursor continua o que o front mandou.
    ultimo = lista[-1]["id_mensagem"] if lista else apos
    return {"mensagens": lista, "ultimo_id_mensagem": ultimo}


def enviar_mensagem(
    conexao: Connection,
    usuario: UsuarioAtual,
    escopo: Escopo,
    id_atendimento: UUID,
    texto: str,
) -> dict[str, Any]:
    """Grava a mensagem (mesmas regras dos chamados). O Realtime entrega aos outros na hora."""
    criada = chamados.enviar_mensagem(conexao, usuario, escopo, id_atendimento, texto)
    # Quem escreve ja leu a conversa ate aqui.
    repositorio.marcar_lido(conexao, escopo, id_atendimento)
    conexao.commit()
    return criada


def marcar_lido(conexao: Connection, escopo: Escopo, id_atendimento: UUID) -> dict[str, int]:
    _no_escopo(conexao, escopo, id_atendimento)
    repositorio.marcar_lido(conexao, escopo, id_atendimento)
    conexao.commit()
    return {"nao_lidas": 0}
