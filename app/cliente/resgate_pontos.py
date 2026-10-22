"""Resgate de pontos Lorenzi+ no checkout do site.

Regra do programa (a mesma do Vulto+ desde mar/2025, scripts/clientes_vulto_carga/clientes_vulto/
resgates.py): R$ 5 de desconto a cada 100 pontos, em multiplos de 100 (como todos os resgates
desde entao). O desconto sai do valor das pecas, nunca do frete, e o saldo tem de cobrir os pontos.
A compra rende pontos sobre o que o cliente pagou (pecas com desconto + frete).
"""

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.cliente.erros import PontosInsuficientes, ResgateAcimaDoValor
from app.cliente.vencimento_pontos import lancar_vencimentos

REAIS_A_CADA_100_PONTOS = Decimal("5")
MULTIPLO_DE_RESGATE = 100
PONTOS_POR_REAL = {"loja": 1, "online": 2}


def desconto(pontos: int) -> Decimal:
    return (Decimal(pontos) / 100 * REAIS_A_CADA_100_PONTOS).quantize(Decimal("0.01"))


def regras() -> dict[str, Any]:
    """O que o site precisa para mostrar o resgate e quanto a compra rende."""
    return {
        "reais_a_cada_100_pontos": REAIS_A_CADA_100_PONTOS,
        "multiplo_de_resgate": MULTIPLO_DE_RESGATE,
        "pontos_por_real_loja": PONTOS_POR_REAL["loja"],
        "pontos_por_real_online": PONTOS_POR_REAL["online"],
    }


def resgatar(
    conexao: Any,
    *,
    id_cliente: UUID,
    id_pedido: UUID,
    id_loja: UUID,
    numero_pedido: str,
    pontos: int,
    valor_das_pecas: Decimal,
) -> Decimal:
    """Tira os pontos do saldo e devolve o desconto em reais. Roda na transacao do checkout."""
    # Vencimentos em dia antes de conferir o saldo; a funcao tambem trava o cliente.
    lancar_vencimentos(conexao, id_cliente)
    saldo = int(
        conexao.execute(
            text(
                "SELECT COALESCE(sum(pontos), 0) FROM movimento_pontos "
                "WHERE id_usuario = CAST(:c AS uuid)"
            ),
            {"c": str(id_cliente)},
        ).scalar_one()
    )
    if pontos > saldo:
        raise PontosInsuficientes(saldo)
    valor = desconto(pontos)
    if valor > valor_das_pecas:
        raise ResgateAcimaDoValor()
    conexao.execute(
        text(
            """
            INSERT INTO movimento_pontos (id_usuario, tipo, pontos, ocorrido_em, descricao,
                                          id_pedido, criado_em)
            VALUES (CAST(:c AS uuid), 'resgate', :p, clock_timestamp(), :d,
                    CAST(:pedido AS uuid), clock_timestamp())
            """
        ),
        {
            "c": str(id_cliente),
            "p": -pontos,
            "d": f"resgate no pedido {numero_pedido}",
            "pedido": str(id_pedido),
        },
    )
    conexao.execute(
        text(
            """
            INSERT INTO resgate_pontos (id_usuario, resgatado_em, pontos, desconto, id_loja,
                                        observacao, id_pedido)
            VALUES (CAST(:c AS uuid), now(), :p, :v, CAST(:l AS uuid), :obs, CAST(:pedido AS uuid))
            """
        ),
        {
            "c": str(id_cliente),
            "p": pontos,
            "v": valor,
            "l": str(id_loja),
            "obs": f"resgate pelo site no pedido {numero_pedido}",
            "pedido": str(id_pedido),
        },
    )
    return valor
