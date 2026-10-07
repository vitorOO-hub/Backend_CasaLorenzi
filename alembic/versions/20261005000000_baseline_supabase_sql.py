"""baseline das migrations SQL do Supabase

Revision ID: 20261005000000
Revises:
Create Date: 2026-10-06 21:30:00
"""

from collections.abc import Sequence


revision: str = "20261005000000"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Estado inicial ja criado pelos arquivos em supabase/migrations."""


def downgrade() -> None:
    """Baseline sem downgrade automatico."""
