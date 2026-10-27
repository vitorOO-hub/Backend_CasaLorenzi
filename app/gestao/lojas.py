"""Dados da loja que o admin edita fora do cadastro: por enquanto, o horario de funcionamento."""

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.erros_auth import SemPermissao
from app.core.horario import DIAS, HorarioFuncionamento
from app.core.papeis import Papel, UsuarioAtual
from app.gestao import auditoria
from app.gestao.erros import LojaNaoEncontrada


def _resumo(horario: HorarioFuncionamento | None) -> str:
    if horario is None:
        return "sem horario"
    dias = horario.model_dump()
    return ", ".join(
        f"{dia} {d['abre']}-{d['fecha']}" if (d := dias[dia]) else f"{dia} fechada" for dia in DIAS
    )


def alterar_horario(
    conexao: Connection,
    usuario: UsuarioAtual,
    id_loja: UUID,
    horario: HorarioFuncionamento | None,
) -> dict[str, Any]:
    """Grava o horario (ou o apaga, com null) e registra na auditoria, na mesma transacao."""
    if usuario.papel is not Papel.ADMIN:
        raise SemPermissao()
    valor = json.dumps(horario.model_dump()) if horario else None
    try:
        nome = conexao.execute(
            text(
                """
                UPDATE loja
                SET horario_funcionamento = CAST(:horario AS jsonb), atualizada_em = now()
                WHERE id_loja = CAST(:id AS uuid)
                RETURNING nome
                """
            ),
            {"id": str(id_loja), "horario": valor},
        ).scalar()
        if nome is None:
            raise LojaNaoEncontrada()
        auditoria.registrar(
            conexao, usuario, "Horario da loja alterado", f"{nome}: {_resumo(horario)}"
        )
        conexao.commit()
    except Exception:
        conexao.rollback()
        raise
    return {"id_loja": id_loja, "horario_funcionamento": horario}
