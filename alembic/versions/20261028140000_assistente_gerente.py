"""Separa conversas do chatbot do gerente das conversas administrativas."""

from collections.abc import Sequence

from alembic import op

revision: str = "20261028140000"
down_revision: str | Sequence[str] | None = "20261028100000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE public.conversa_assistente DROP CONSTRAINT chk_conversa_assistente_tipo"
    )
    op.execute(
        "ALTER TABLE public.conversa_assistente ADD CONSTRAINT chk_conversa_assistente_tipo "
        "CHECK (tipo IN ('cliente', 'interno', 'interno_gerente'))"
    )


def downgrade() -> None:
    op.execute("DELETE FROM public.conversa_assistente WHERE tipo = 'interno_gerente'")
    op.execute(
        "ALTER TABLE public.conversa_assistente DROP CONSTRAINT chk_conversa_assistente_tipo"
    )
    op.execute(
        "ALTER TABLE public.conversa_assistente ADD CONSTRAINT chk_conversa_assistente_tipo "
        "CHECK (tipo IN ('cliente', 'interno'))"
    )
