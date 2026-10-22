"""Lorenzi+: resgate de pontos no checkout e devolucao quando a compra e cancelada

Revision ID: 20261024120000
Revises: 20261024110000
Create Date: 2026-10-24 12:00:00

- `resgate_pontos.id_pedido`: o pedido em que os pontos viraram desconto (resgate feito pelo site).
- O trigger de pontos do pedido (20261024100000) passa a devolver os pontos resgatados quando a
  compra e cancelada: um `estorno` positivo ligado ao pedido, com validade de 365 dias, e o resgate
  ganha a observacao. A devolucao acontece uma vez so.
- Na conta do credito da compra entram so `credito` e `estorno` negativo: a devolucao do resgate
  (estorno positivo) nao e credito de compra.
- O inicio dos pontos (gravado na funcao pela 20261024100000) e lido da funcao instalada e mantido.
"""

import re
from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "20261024120000"
down_revision: str | Sequence[str] | None = "20261024110000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEVOLUCAO = """
    -- Compra cancelada devolve, uma vez, os pontos resgatados nela.
    IF cancelado AND NEW.id_cliente IS NOT NULL THEN
        SELECT COALESCE(-sum(pontos) FILTER (WHERE tipo = 'resgate'), 0),
               COALESCE(sum(pontos) FILTER (WHERE tipo = 'estorno' AND pontos > 0), 0)
        INTO resgatado, devolvido
        FROM movimento_pontos WHERE id_usuario = NEW.id_cliente AND id_pedido = NEW.id_pedido;
        IF resgatado > 0 AND devolvido = 0 THEN
            agora := clock_timestamp();
            INSERT INTO movimento_pontos (id_usuario, tipo, pontos, ocorrido_em, vence_em,
                                          descricao, id_pedido, criado_em)
            VALUES (NEW.id_cliente, 'estorno', resgatado, agora, agora + interval '365 days',
                    'pontos devolvidos: compra ' || NEW.numero_pedido || ' cancelada',
                    NEW.id_pedido, agora);
            UPDATE resgate_pontos
            SET observacao = concat_ws('; ', observacao, 'compra cancelada, pontos devolvidos')
            WHERE id_pedido = NEW.id_pedido;
        END IF;
    END IF;
"""


def _funcao(inicio: str, *, com_devolucao: bool) -> str:
    filtro_atual = (
        "(tipo = 'credito' OR (tipo = 'estorno' AND pontos < 0))"
        if com_devolucao
        else "tipo IN ('credito', 'estorno')"
    )
    return f"""
CREATE OR REPLACE FUNCTION public.pedido_credita_pontos()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $fn$
DECLARE
    cli uuid;
    desejado integer;
    atual integer;
    dif integer;
    pontua boolean;
    cancelado boolean;
    resgatado integer;
    devolvido integer;
    agora timestamptz;
BEGIN
    IF NEW.criado_em < TIMESTAMPTZ '{inicio}' THEN
        RETURN NEW;
    END IF;
    SELECT s.codigo IN ('pago', 'separado', 'entregue'), s.codigo = 'cancelado'
    INTO pontua, cancelado
    FROM status_pedido s WHERE s.id_status_pedido = NEW.id_status_pedido;

    FOREACH cli IN ARRAY ARRAY[
        CASE WHEN TG_OP = 'UPDATE' THEN OLD.id_cliente END, NEW.id_cliente
    ] LOOP
        CONTINUE WHEN cli IS NULL;
        CONTINUE WHEN NOT EXISTS (
            SELECT 1 FROM usuario u JOIN tipo_usuario t ON t.id_tipo_usuario = u.id_tipo_usuario
            WHERE u.id_usuario = cli AND t.codigo = 'cliente'
        );
        desejado := CASE WHEN cli = NEW.id_cliente AND COALESCE(pontua, false)
                         THEN public.pontos_da_compra(NEW.valor_total, NEW.canal_venda) ELSE 0 END;
        SELECT COALESCE(sum(pontos), 0) INTO atual FROM movimento_pontos
        WHERE id_usuario = cli AND id_pedido = NEW.id_pedido AND {filtro_atual};
        dif := desejado - atual;
        -- clock_timestamp: credito e estorno na mesma transacao ficam na ordem em que aconteceram.
        agora := clock_timestamp();
        IF dif > 0 THEN
            INSERT INTO movimento_pontos (id_usuario, tipo, pontos, ocorrido_em, vence_em,
                                          descricao, id_pedido, criado_em)
            VALUES (cli, 'credito', dif, agora, agora + interval '365 days',
                    'compra ' || NEW.numero_pedido, NEW.id_pedido, agora);
        ELSIF dif < 0 THEN
            INSERT INTO movimento_pontos (id_usuario, tipo, pontos, ocorrido_em, descricao,
                                          id_pedido, criado_em)
            VALUES (cli, 'estorno', dif, agora,
                    'estorno da compra ' || NEW.numero_pedido, NEW.id_pedido, agora);
        END IF;
    END LOOP;
{DEVOLUCAO if com_devolucao else ""}
    RETURN NEW;
END
$fn$
"""


def _inicio_dos_pontos() -> str:
    definicao = (
        op.get_bind()
        .execute(text("SELECT pg_get_functiondef('public.pedido_credita_pontos()'::regprocedure)"))
        .scalar_one()
    )
    achado = re.search(r"NEW\.criado_em < TIMESTAMPTZ '([^']+)'", definicao)
    if achado is None:
        raise RuntimeError("inicio dos pontos nao encontrado em pedido_credita_pontos()")
    return achado.group(1)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE public.resgate_pontos ADD COLUMN IF NOT EXISTS id_pedido UUID "
        "REFERENCES public.pedido (id_pedido) ON UPDATE CASCADE ON DELETE SET NULL"
    )
    op.execute(_funcao(_inicio_dos_pontos(), com_devolucao=True))


def downgrade() -> None:
    op.execute(_funcao(_inicio_dos_pontos(), com_devolucao=False))
    op.execute("ALTER TABLE public.resgate_pontos DROP COLUMN IF EXISTS id_pedido")
