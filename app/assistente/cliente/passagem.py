"""Passagem da conversa do assistente para um atendente de verdade.

O chamado nasce com o motivo, o resumo do assistente (quando ele escreveu um) e a transcricao da
conversa, para o cliente nao precisar repetir o problema. Vale para a transferencia pedida pelo
modelo e para a automatica (quando o assistente nao consegue responder com seguranca).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.engine import Connection

from app.assistente.cliente import repositorio
from app.cliente import service as cliente
from app.core.papeis import UsuarioAtual

# A rota de chamado do cliente aceita ate 4000 caracteres na descricao; seguimos o mesmo teto.
LIMITE_DESCRICAO = 4000
LIMITE_ASSUNTO = 200
MENSAGENS_NA_TRANSCRICAO = 40
CABECALHO = "Chamado aberto pelo assistente do site."
NOMES = {"usuario": "Cliente", "assistente": "Assistente"}


def montar_descricao(mensagens: list[dict[str, Any]], *, motivo: str, resumo: str | None) -> str:
    """Motivo e resumo no topo; abaixo, a conversa. Se nao couber, ficam as mais recentes."""
    topo = [CABECALHO, f"Motivo: {motivo}"]
    if resumo:
        topo.append(f"Resumo do assistente: {resumo}")
    inicio = "\n".join(topo) + "\n\nConversa com o assistente:"
    linhas = [f"{NOMES.get(m['autor'], m['autor'])}: {m['texto'].strip()}" for m in mensagens]
    espaco = LIMITE_DESCRICAO - len(inicio) - len("\n[mensagens anteriores omitidas]")
    cabem: list[str] = []
    for linha in reversed(linhas):
        if len(linha) + 1 > espaco:
            break
        cabem.insert(0, linha)
        espaco -= len(linha) + 1
    if len(cabem) < len(linhas):
        cabem.insert(0, "[mensagens anteriores omitidas]")
    return "\n".join([inicio, *cabem])[:LIMITE_DESCRICAO]


def abrir_chamado_da_conversa(
    conexao: Connection,
    usuario: UsuarioAtual,
    id_conversa: UUID | None,
    *,
    assunto: str,
    motivo: str,
    categoria: str = "outro",
    resumo: str | None = None,
) -> dict[str, Any]:
    """Abre o chamado do cliente do token com a conversa anexada. Quem chama marca a conversa."""
    mensagens = (
        repositorio.mensagens_visiveis(conexao, id_conversa, MENSAGENS_NA_TRANSCRICAO)
        if id_conversa
        else []
    )
    return cliente.criar_chamado(
        conexao,
        usuario,
        {
            "assunto": assunto.strip()[:LIMITE_ASSUNTO] or "Atendimento pelo assistente",
            "categoria": categoria,
            "descricao": montar_descricao(mensagens, motivo=motivo, resumo=resumo),
        },
    )
