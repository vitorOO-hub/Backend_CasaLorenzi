"""Utilitarios compartilhados pelos repositorios SQL."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy.engine import Connection


def serializar_valor(valor: object) -> object:
    if isinstance(valor, UUID):
        return str(valor)
    if isinstance(valor, Decimal):
        return str(valor)
    if hasattr(valor, "isoformat"):
        return valor.isoformat()
    return valor


def serializar_linha(linha: dict[str, object]) -> dict[str, object]:
    return {chave: serializar_valor(valor) for chave, valor in linha.items()}


def executar_sql(conexao: Connection, sql: str, parametros: tuple[object, ...] = ()):
    return conexao.exec_driver_sql(sql, parametros)


def buscar_um(
    conexao: Connection,
    sql: str,
    parametros: tuple[object, ...] = (),
) -> dict[str, object] | None:
    linha = executar_sql(conexao, sql, parametros).mappings().first()
    return dict(linha) if linha else None


def buscar_todos(
    conexao: Connection,
    sql: str,
    parametros: tuple[object, ...] = (),
) -> list[dict[str, object]]:
    return [dict(linha) for linha in executar_sql(conexao, sql, parametros).mappings().all()]
