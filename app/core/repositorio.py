"""Utilitarios compartilhados pelos repositorios SQL."""

from decimal import Decimal
from uuid import UUID


def normalizar_id(valor: object) -> int | UUID:
    """Aceita ids antigos numericos nos testes e UUIDs no Supabase atual."""
    if isinstance(valor, int) and not isinstance(valor, bool):
        return valor
    texto = str(valor).strip()
    if texto.isdigit():
        return int(texto)
    return UUID(texto)


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


def serializar_linhas(linhas: list[dict[str, object]]) -> list[dict[str, object]]:
    return [serializar_linha(linha) for linha in linhas]


def limpar_nulos(dados: dict[str, object]) -> dict[str, object]:
    return {chave: valor for chave, valor in dados.items() if valor is not None}


def normalizar_ids_no_dicionario(dados: dict[str, object]) -> dict[str, object]:
    normalizados = dados.copy()
    for chave, valor in dados.items():
        if chave.startswith("id_") and valor is not None:
            normalizados[chave] = normalizar_id(valor)
    return normalizados


def montar_insert(tabela: str, dados: dict[str, object]) -> tuple[str, tuple[object, ...]]:
    colunas = ", ".join(dados)
    marcadores = ", ".join(["%s"] * len(dados))
    sql = f"INSERT INTO {tabela} ({colunas}) VALUES ({marcadores}) RETURNING *"
    return sql, tuple(dados.values())


def montar_update(
    tabela: str,
    coluna_id: str,
    id_registro: object,
    dados: dict[str, object],
    *,
    coluna_data: str | None = None,
) -> tuple[str, tuple[object, ...]]:
    atribuicoes = [f"{coluna} = %s" for coluna in dados]
    valores = list(dados.values())
    if coluna_data:
        atribuicoes.append(f"{coluna_data} = now()")
    sql = f"UPDATE {tabela} SET {', '.join(atribuicoes)} WHERE {coluna_id} = %s RETURNING *"
    valores.append(id_registro)
    return sql, tuple(valores)
