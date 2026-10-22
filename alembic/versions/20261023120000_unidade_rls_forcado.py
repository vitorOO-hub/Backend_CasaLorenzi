"""unidade: RLS forcado, como nas outras tabelas

Revision ID: 20261023120000
Revises: 20261023110000
Create Date: 2026-10-23 12:00:00

A migration 20261020120000 ligou o RLS de `unidade` sem forca-lo. Sem policy, quem le e escreve
continua sendo so a conexao do FastAPI (que ignora RLS); forcar fecha a brecha para o dono da
tabela, igual as demais (test_rls_ligado_e_forcado_em_todas_as_tabelas).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261023120000"
down_revision: str | Sequence[str] | None = "20261023110000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE public.unidade FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE public.unidade NO FORCE ROW LEVEL SECURITY")
