from __future__ import annotations

from typing import Any


def get_stock(sku: str, loja: str) -> dict[str, Any]:
    stock = {"Savassi": 5, "Barra": 0, "Ibirapuera": 12}
    if sku != "CAM-001":
        return {"encontrado": False, "sku": sku, "loja": loja}
    if loja == "REDE":
        return {"encontrado": True, "sku": sku, "loja": loja, "quantidade": sum(stock.values())}
    quantity = stock.get(loja)
    if quantity is None:
        return {"encontrado": False, "sku": sku, "loja": loja}
    return {"encontrado": True, "sku": sku, "loja": loja, "quantidade": quantity}


def get_points(cliente_ref: str) -> dict[str, Any]:
    if cliente_ref != "CLIENTE-DEMO-A":
        return {"encontrado": False, "cliente_ref": cliente_ref}
    return {
        "encontrado": True,
        "cliente_ref": cliente_ref,
        "pontos_ativos": 240,
        "pontos_a_vencer": 60,
        "data_vencimento": "31/10/2026",
    }


def get_store_hours(loja: str, dia: str) -> dict[str, Any]:
    hours = {
        "Savassi": {"domingo": None},
        "Barra": {"domingo": ["12h", "18h"]},
    }
    normalized_store = loja.strip().title()
    normalized_day = dia.strip().casefold()
    if normalized_store not in hours or normalized_day not in hours[normalized_store]:
        return {"encontrado": False, "loja": loja, "dia": dia}
    times = hours[normalized_store][normalized_day]
    return {
        "encontrado": True,
        "loja": normalized_store,
        "dia": normalized_day,
        "fechada": times is None,
        "abre": times[0] if times else None,
        "fecha": times[1] if times else None,
    }


def get_sales_summary(dias: int) -> dict[str, Any]:
    if dias != 7:
        return {"encontrado": False, "dias": dias}
    return {"encontrado": True, "dias": dias, "pedidos": 18, "faturamento": 4320.0}


TOOL_FUNCTIONS = {
    "get_stock": get_stock,
    "get_points": get_points,
    "get_store_hours": get_store_hours,
    "get_sales_summary": get_sales_summary,
}

TOOL_DECLARATIONS = [
    {
        "name": "get_stock",
        "description": (
            "Consulta quantidade de um SKU em uma loja ou na rede inteira. "
            "Use REDE para total das lojas."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sku": {"type": "string"},
                "loja": {"type": "string", "enum": ["Savassi", "Barra", "Ibirapuera", "REDE"]},
            },
            "required": ["sku", "loja"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_points",
        "description": (
            "Consulta saldo de pontos e pontos a vencer de uma referencia ficticia de cliente."
        ),
        "parameters": {
            "type": "object",
            "properties": {"cliente_ref": {"type": "string"}},
            "required": ["cliente_ref"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_store_hours",
        "description": "Consulta horario de funcionamento de uma loja em um dia da semana.",
        "parameters": {
            "type": "object",
            "properties": {
                "loja": {"type": "string", "enum": ["Savassi", "Barra"]},
                "dia": {"type": "string"},
            },
            "required": ["loja", "dia"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_sales_summary",
        "description": "Consulta resumo de pedidos e faturamento para um periodo em dias.",
        "parameters": {
            "type": "object",
            "properties": {"dias": {"type": "integer"}},
            "required": ["dias"],
            "additionalProperties": False,
        },
    },
]


def run_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    function = TOOL_FUNCTIONS.get(name)
    if function is None:
        return {"erro": "ferramenta_desconhecida"}
    try:
        return function(**arguments)
    except (TypeError, ValueError):
        return {"erro": "argumentos_invalidos"}


def normalize_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.strip().casefold() if isinstance(value, str) else value
        for key, value in arguments.items()
    }


def score_tool_calls(
    actual: list[dict[str, Any]], expected: list[dict[str, Any]]
) -> tuple[bool, str]:
    normalized_actual = [
        {"nome": item["nome"], "argumentos": normalize_arguments(item["argumentos"])}
        for item in actual
    ]
    normalized_expected = [
        {"nome": item["nome"], "argumentos": normalize_arguments(item["argumentos"])}
        for item in expected
    ]
    passed = normalized_actual == normalized_expected
    return passed, "" if passed else f"esperado={normalized_expected}; recebido={normalized_actual}"
