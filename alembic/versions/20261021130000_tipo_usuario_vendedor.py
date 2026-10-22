"""tipo_usuario: novo tipo vendedor

Revision ID: 20261021130000
Revises: 20261021120000
Create Date: 2026-10-21 13:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261021130000"
down_revision: str | Sequence[str] | None = "20261021120000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO public.tipo_usuario (codigo, nome, descricao, ordem)
        VALUES ('vendedor', 'Vendedor', 'Usuario responsavel por vendas na loja.', 6)
        ON CONFLICT ON CONSTRAINT uq_tipo_usuario_codigo DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM public.tipo_usuario WHERE codigo = 'vendedor'")
