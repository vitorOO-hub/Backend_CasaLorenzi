"""rls forcado e privilegios minimos nas tabelas de transferencia de estoque

Revision ID: 20261007110000
Revises: 20261007103000
Create Date: 2026-10-07 11:00:00

A revisao 20261007103000 criou as tabelas de transferencia sem ligar o RLS nem tirar os privilegios
de anon e authenticated. Regra do projeto: toda tabela nova nasce com RLS ligado e forcado e sem
privilegio para o front. Aqui nao ha policy de proposito: sem policy, so a API (que conecta com
credencial privilegiada e confere papel e loja no codigo) acessa estas tabelas.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261007110000"
down_revision: str | Sequence[str] | None = "20261007103000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABELAS = (
    "tipo_transferencia_estoque",
    "status_transferencia_estoque",
    "transferencia_estoque",
)


def upgrade() -> None:
    for tabela in TABELAS:
        op.execute(f"ALTER TABLE public.{tabela} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE public.{tabela} FORCE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON public.{tabela} FROM anon, authenticated")


def downgrade() -> None:
    # Volta so o FORCE (o RLS ligado e inofensivo e o painel do Supabase o liga sozinho).
    for tabela in reversed(TABELAS):
        op.execute(f"ALTER TABLE public.{tabela} NO FORCE ROW LEVEL SECURITY")
