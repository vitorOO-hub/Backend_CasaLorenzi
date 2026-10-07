"""atendimento.assunto, o titulo do chamado exibido na fila

Revision ID: 20261007000500
Revises: 20261007000400
Create Date: 2026-10-07 00:05:00

A fila do dashboard mostra o assunto de cada chamado. A coluna e nullable porque os chamados
ja existentes e o POST /atendimentos antigo nao a enviam; a API cai para o nome da categoria.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261007000500"
down_revision: str | Sequence[str] | None = "20261007000400"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SUBIDA = (
    "ALTER TABLE public.atendimento ADD COLUMN IF NOT EXISTS assunto TEXT",
    """
    DO $bloco$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_atendimento_assunto') THEN
            ALTER TABLE public.atendimento
                ADD CONSTRAINT chk_atendimento_assunto
                CHECK (assunto IS NULL OR length(btrim(assunto)) BETWEEN 1 AND 200);
        END IF;
    END
    $bloco$
    """,
    # Apoia a fila (nao resolvidos de uma loja, mais antigos primeiro) e as metricas por periodo.
    "CREATE INDEX IF NOT EXISTS idx_atendimento_loja_aberto_em "
    "ON public.atendimento (id_loja, aberto_em)",
    "CREATE INDEX IF NOT EXISTS idx_mensagem_atendimento_enviada "
    "ON public.mensagem (id_atendimento, enviada_em)",
)

DESCIDA = (
    "DROP INDEX IF EXISTS public.idx_mensagem_atendimento_enviada",
    "DROP INDEX IF EXISTS public.idx_atendimento_loja_aberto_em",
    "ALTER TABLE public.atendimento DROP CONSTRAINT IF EXISTS chk_atendimento_assunto",
    "ALTER TABLE public.atendimento DROP COLUMN IF EXISTS assunto",
)


def upgrade() -> None:
    for comando in SUBIDA:
        op.execute(comando)


def downgrade() -> None:
    for comando in DESCIDA:
        op.execute(comando)
