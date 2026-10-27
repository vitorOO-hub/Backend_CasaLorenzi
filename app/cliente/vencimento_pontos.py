"""Vencimento dos pontos Lorenzi+ (antigo Vulto+): o que venceu e o que esta para vencer.

Regra do programa (a mesma da carga em scripts/clientes_vulto_carga/clientes_vulto/pontos.py):
cada credito vale 365 dias (`vence_em`) e o que sai do saldo consome primeiro os pontos mais
antigos. Credito sem `vence_em` (ajuste de conciliacao, por exemplo) nao vence.

A carga ja lancou tudo o que venceu ate a data de referencia dela (CORTE_DA_CARGA). Daqui para a
frente, cada lote que vence vira uma linha `vencimento` com `ocorrido_em` igual ao `vence_em` do
lote, o que torna o lancamento idempotente: rodar de novo nao duplica nada.

Quem grava e a funcao `public.lancar_vencimentos_pontos` do banco (migracao 20261024100000), que o
pg_cron roda todo dia e a leitura do Lorenzi+ chama antes de mostrar o saldo. Este modulo tem a
mesma regra em Python para o aviso dos proximos 30 dias; os testes de banco conferem que as duas
dao o mesmo resultado.

O saldo na data de corte e repartido entre os lotes ainda vivos do mais novo para o mais antigo
(quem consome primeiro os antigos deixa o que sobra nos novos). Depois do corte, cada saida
consome os lotes vivos na ordem em que entraram (o estorno de uma compra sai primeiro do credito
dela), e lote vencido nao e mais consumido.
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.engine import Connection

SP = ZoneInfo("America/Sao_Paulo")
# Data de referencia da carga do Vulto+ (pontos contados ate 21/10/2026, fim do dia).
CORTE_DA_CARGA = datetime(2026, 10, 21, 23, 59, 59, tzinfo=SP)
JANELA_DO_AVISO = timedelta(days=30)


class _Lote:
    __slots__ = ("entrada", "id_pedido", "resta", "vence_em")

    def __init__(
        self, entrada: datetime, resta: int, vence_em: datetime | None, id_pedido: Any = None
    ) -> None:
        self.entrada, self.resta, self.vence_em = entrada, resta, vence_em
        self.id_pedido = id_pedido


def _movimentos(conexao: Connection, id_cliente: UUID) -> Sequence[Any]:
    return conexao.execute(
        text(
            """
            SELECT tipo, pontos, ocorrido_em, vence_em, id_pedido
            FROM movimento_pontos
            WHERE id_usuario = CAST(:cliente AS uuid)
            ORDER BY ocorrido_em, criado_em, id_movimento
            """
        ),
        {"cliente": str(id_cliente)},
    ).all()


def _lotes_no_corte(movimentos: Sequence[Any]) -> list[_Lote]:
    antes = [m for m in movimentos if m.ocorrido_em <= CORTE_DA_CARGA]
    saldo = max(sum(m.pontos for m in antes), 0)
    vivos = [
        m for m in antes if m.pontos > 0 and (m.vence_em is None or m.vence_em > CORTE_DA_CARGA)
    ]
    lotes = []
    for m in reversed(vivos):
        parte = min(m.pontos, saldo)
        saldo -= parte
        lotes.append(_Lote(m.ocorrido_em, parte, m.vence_em, m.id_pedido))
    lotes.reverse()
    return lotes


def _consumir(lotes: list[_Lote], pontos: int, quando: datetime, id_pedido: Any = None) -> None:
    # Estorno de compra sai primeiro do credito da propria compra; o resto, dos mais antigos.
    da_compra = [lote for lote in lotes if id_pedido is not None and lote.id_pedido == id_pedido]
    for lote in [*da_compra, *lotes]:
        if pontos <= 0:
            return
        if lote.resta <= 0 or (lote.vence_em is not None and lote.vence_em <= quando):
            continue
        usado = min(lote.resta, pontos)
        lote.resta -= usado
        pontos -= usado


def calcular(
    movimentos: Sequence[Any], agora: datetime
) -> tuple[list[dict[str, Any]], list[_Lote]]:
    """Vencimentos que faltam lancar ate `agora` e os lotes com o que resta em cada um."""
    lotes = _lotes_no_corte(movimentos)
    lancados: dict[datetime, int] = {}
    depois = []
    for m in movimentos:
        if m.ocorrido_em <= CORTE_DA_CARGA:
            continue
        if m.tipo == "vencimento":
            lancados[m.ocorrido_em] = lancados.get(m.ocorrido_em, 0) - m.pontos
        else:
            depois.append(m)

    faltam: list[dict[str, Any]] = []

    def vencer_ate(limite: datetime, inclusive: bool) -> None:
        datas = sorted(
            {
                lote.vence_em
                for lote in lotes
                if lote.vence_em is not None
                and lote.vence_em > CORTE_DA_CARGA
                and (lote.vence_em <= limite if inclusive else lote.vence_em < limite)
                and lote.resta > 0
            }
        )
        for data in datas:
            do_dia = [lote for lote in lotes if lote.vence_em == data]
            total = sum(lote.resta for lote in do_dia)
            falta = total - lancados.pop(data, 0)
            if falta > 0:
                entrada = min(lote.entrada for lote in do_dia)
                faltam.append(
                    {
                        "pontos": -falta,
                        "ocorrido_em": data,
                        "descricao": f"vencimento dos pontos de {entrada.astimezone(SP):%d/%m/%Y}",
                    }
                )
            for lote in do_dia:
                lote.resta = 0

    for m in depois:
        vencer_ate(m.ocorrido_em, inclusive=False)
        if m.pontos > 0:
            lotes.append(_Lote(m.ocorrido_em, m.pontos, m.vence_em, m.id_pedido))
        else:
            _consumir(lotes, -m.pontos, m.ocorrido_em, m.id_pedido)
    vencer_ate(agora, inclusive=True)
    return faltam, lotes


def lancar_vencimentos(
    conexao: Connection, id_cliente: UUID, agora: datetime | None = None
) -> dict[str, Any]:
    """Lanca os vencimentos que faltam (funcao do banco, com trava por cliente) e devolve o aviso
    dos proximos 30 dias. Quem chama confirma a transacao."""
    agora = agora or datetime.now(UTC)
    conexao.execute(
        text("SELECT public.lancar_vencimentos_pontos(CAST(:cliente AS uuid), :agora)"),
        {"cliente": str(id_cliente), "agora": agora},
    )
    _, lotes = calcular(_movimentos(conexao, id_cliente), agora)
    return aviso(lotes, agora)


def aviso(
    lotes: Sequence[_Lote], agora: datetime, janela: timedelta = JANELA_DO_AVISO
) -> dict[str, Any]:
    """Pontos que vencem dentro da janela (30 dias por padrao), por data de vencimento."""
    proximos: dict[datetime, int] = {}
    for lote in lotes:
        if lote.resta > 0 and lote.vence_em is not None and agora < lote.vence_em <= agora + janela:
            proximos[lote.vence_em] = proximos.get(lote.vence_em, 0) + lote.resta
    return {
        "pontos_a_vencer": sum(proximos.values()),
        "proximos_vencimentos": [
            {"vence_em": data, "pontos": pontos} for data, pontos in sorted(proximos.items())
        ],
    }


def a_vencer_por_cliente(
    movimentos: Sequence[Any], agora: datetime, janela: timedelta
) -> dict[Any, dict[str, Any]]:
    """Mesma conta do Lorenzi+, para varios clientes de uma vez. `movimentos` traz `id_usuario`
    e vem ordenado por cliente e data. So entram clientes com pontos a vencer na janela."""
    por_cliente: dict[Any, list[Any]] = {}
    for m in movimentos:
        por_cliente.setdefault(m.id_usuario, []).append(m)
    resultado = {}
    for id_usuario, dele in por_cliente.items():
        _, lotes = calcular(dele, agora)
        resumo = aviso(lotes, agora, janela)
        if resumo["pontos_a_vencer"] > 0:
            resultado[id_usuario] = resumo
    return resultado


def pontos_a_vencer_da_base(
    conexao: Connection, janela: timedelta, agora: datetime | None = None
) -> dict[Any, dict[str, Any]]:
    """Clientes com pontos vencendo em (agora, agora + janela]. So le: os vencimentos ja passados
    sao descontados na conta (o lancamento e do pg_cron e da leitura do Lorenzi+)."""
    agora = agora or datetime.now(UTC)
    movimentos = conexao.execute(
        text(
            """
            SELECT m.id_usuario, m.tipo, m.pontos, m.ocorrido_em, m.vence_em, m.id_pedido
            FROM movimento_pontos m
            WHERE m.id_usuario IN (
                SELECT id_usuario FROM movimento_pontos
                WHERE pontos > 0 AND vence_em > :agora AND vence_em <= :limite
            )
            ORDER BY m.id_usuario, m.ocorrido_em, m.criado_em, m.id_movimento
            """
        ),
        {"agora": agora, "limite": agora + janela},
    ).all()
    return a_vencer_por_cliente(movimentos, agora, janela)
