"""ajuste de estoque: motivo da recusa

Revision ID: 20261007170000
Revises: 20261007162000
Create Date: 2026-10-07 17:00:00

Quem recusa um ajuste de inventario explica o motivo ao operador. O motivo so existe em ajuste
recusado, e um ajuste recusado sempre tem motivo.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261007170000"
down_revision: str | Sequence[str] | None = "20261007162000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SUBIDA = (
    "ALTER TABLE public.ajuste_estoque ADD COLUMN IF NOT EXISTS motivo_recusa TEXT",
    "ALTER TABLE public.ajuste_estoque DROP CONSTRAINT IF EXISTS chk_ajuste_estoque_motivo_recusa",
    """
    ALTER TABLE public.ajuste_estoque ADD CONSTRAINT chk_ajuste_estoque_motivo_recusa CHECK (
        (status = 'rejeitado' AND length(trim(COALESCE(motivo_recusa, ''))) > 0)
        OR (status <> 'rejeitado' AND motivo_recusa IS NULL)
    ) NOT VALID
    """,
    # Recusas que ja existiam (se houver) ficam com um motivo padrao antes de validar a regra.
    """
    UPDATE public.ajuste_estoque SET motivo_recusa = 'Sem motivo informado'
    WHERE status = 'rejeitado' AND length(trim(COALESCE(motivo_recusa, ''))) = 0
    """,
    "ALTER TABLE public.ajuste_estoque VALIDATE CONSTRAINT chk_ajuste_estoque_motivo_recusa",
)

DESCIDA = (
    "ALTER TABLE public.ajuste_estoque DROP CONSTRAINT IF EXISTS chk_ajuste_estoque_motivo_recusa",
    "ALTER TABLE public.ajuste_estoque DROP COLUMN IF EXISTS motivo_recusa",
)


def upgrade() -> None:
    for comando in SUBIDA:
        op.execute(comando)


def downgrade() -> None:
    for comando in DESCIDA:
        op.execute(comando)
