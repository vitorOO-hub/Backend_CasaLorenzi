"""Vencimento dos pontos Vulto+: lanca no extrato o que venceu e conta o que esta para vencer.

Regra do programa (a mesma da carga em scripts/clientes_vulto_carga/clientes_vulto/pontos.py):
cada credito vale 365 dias (`vence_em`) e o que sai do saldo consome primeiro os pontos mais
antigos. Credito sem `vence_em` (ajuste de conciliacao, por exemplo) nao vence.

A carga ja lancou tudo o que venceu ate a data de referencia dela (CORTE_DA_CARGA). Daqui para a
frente, cada lote que vence e lancado aqui como uma linha `vencimento` com `ocorrido_em` igual ao
`vence_em` do lote, o que torna o lancamento idempotente: rodar de novo nao duplica nada.

O saldo na data de corte e repartido entre os lotes ainda vivos do mais novo para o mais antigo
(quem consome primeiro os antigos deixa o que sobra nos novos). Depois do corte, cada saida
consome os lotes vivos na ordem em que entraram, e lote vencido nao e mais consumido.
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
    __slots__ = ("entrada", "resta", "vence_em")

    def __init__(self, entrada: datetime, resta: int, vence_em: datetime | None) -> None:
        self.entrada, self.resta, self.vence_em = entrada, resta, vence_em


def _movimentos(conexao: Connection, id_cliente: UUID) -> Sequence[Any]:
    return conexao.execute(
        text(
            """
            SELECT tipo, pontos, ocorrido_em, vence_em
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
        lotes.append(_Lote(m.ocorrido_em, parte, m.vence_em))
    lotes.reverse()
    return lotes


def _consumir(lotes: list[_Lote], pontos: int, quando: datetime) -> None:
    for lote in lotes:
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
            lotes.append(_Lote(m.ocorrido_em, m.pontos, m.vence_em))
        else:
            _consumir(lotes, -m.pontos, m.ocorrido_em)
    vencer_ate(agora, inclusive=True)
    return faltam, lotes


def lancar_vencimentos(
    conexao: Connection, id_cliente: UUID, agora: datetime | None = None
) -> dict[str, Any]:
    """Lanca os vencimentos que faltam e devolve o aviso dos proximos 30 dias. Quem chama confirma
    a transacao. A trava por cliente evita que duas leituras ao mesmo tempo lancem em dobro."""
    agora = agora or datetime.now(UTC)
    conexao.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(CAST(:cliente AS text), 0))"),
        {"cliente": str(id_cliente)},
    )
    faltam, lotes = calcular(_movimentos(conexao, id_cliente), agora)
    for v in faltam:
        conexao.execute(
            text(
                """
                INSERT INTO movimento_pontos (id_usuario, tipo, pontos, ocorrido_em, descricao)
                VALUES (CAST(:cliente AS uuid), 'vencimento', :pontos, :ocorrido_em, :descricao)
                """
            ),
            {"cliente": str(id_cliente), **v},
        )
    return aviso(lotes, agora)


def aviso(lotes: Sequence[_Lote], agora: datetime) -> dict[str, Any]:
    """Pontos que vencem nos proximos 30 dias, por data de vencimento."""
    proximos: dict[datetime, int] = {}
    for lote in lotes:
        if (
            lote.resta > 0
            and lote.vence_em is not None
            and agora < lote.vence_em <= agora + JANELA_DO_AVISO
        ):
            proximos[lote.vence_em] = proximos.get(lote.vence_em, 0) + lote.resta
    return {
        "pontos_a_vencer": sum(proximos.values()),
        "proximos_vencimentos": [
            {"vence_em": data, "pontos": pontos} for data, pontos in sorted(proximos.items())
        ],
    }
