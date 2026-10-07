"""atendimento.id_loja, preenchido a partir do pedido

Revision ID: 20261007000000
Revises: 20261006213000
Create Date: 2026-10-07 00:00:00

O escopo por loja do atendimento precisa de id_loja. A coluna e nullable porque o
POST /atendimentos atual nao envia loja; o trigger a preenche pelo pedido quando houver.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261007000000"
down_revision: str | Sequence[str] | None = "20261006213000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SUBIDA = (
    "ALTER TABLE public.atendimento ADD COLUMN IF NOT EXISTS id_loja UUID",
    """
    DO $bloco$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_atendimento_loja') THEN
            ALTER TABLE public.atendimento
                ADD CONSTRAINT fk_atendimento_loja
                FOREIGN KEY (id_loja) REFERENCES public.loja (id_loja)
                ON UPDATE CASCADE ON DELETE RESTRICT;
        END IF;
    END
    $bloco$
    """,
    "CREATE INDEX IF NOT EXISTS idx_atendimento_id_loja ON public.atendimento (id_loja)",
    """
    CREATE OR REPLACE FUNCTION public.preencher_id_loja_atendimento()
    RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = public, pg_temp
    AS $fn$
    BEGIN
        IF NEW.id_loja IS NULL AND NEW.id_pedido IS NOT NULL THEN
            SELECT p.id_loja INTO NEW.id_loja
            FROM public.pedido p
            WHERE p.id_pedido = NEW.id_pedido;
        END IF;
        RETURN NEW;
    END
    $fn$
    """,
    "DROP TRIGGER IF EXISTS trg_atendimento_preencher_id_loja ON public.atendimento",
    """
    CREATE TRIGGER trg_atendimento_preencher_id_loja
    BEFORE INSERT ON public.atendimento
    FOR EACH ROW EXECUTE FUNCTION public.preencher_id_loja_atendimento()
    """,
)

DESCIDA = (
    "DROP TRIGGER IF EXISTS trg_atendimento_preencher_id_loja ON public.atendimento",
    "DROP FUNCTION IF EXISTS public.preencher_id_loja_atendimento()",
    "DROP INDEX IF EXISTS public.idx_atendimento_id_loja",
    "ALTER TABLE public.atendimento DROP CONSTRAINT IF EXISTS fk_atendimento_loja",
    "ALTER TABLE public.atendimento DROP COLUMN IF EXISTS id_loja",
)


def upgrade() -> None:
    for comando in SUBIDA:
        op.execute(comando)


def downgrade() -> None:
    for comando in DESCIDA:
        op.execute(comando)
