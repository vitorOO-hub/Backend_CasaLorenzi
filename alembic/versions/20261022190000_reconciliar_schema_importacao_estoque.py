"""reconcilia schema de estoque para a carga Vulto e aceita saldo negativo

Revision ID: 20261022190000
Revises: 20261022180000
Create Date: 2026-10-22 19:00:00

A revisao 20261022180000 pode aparecer aplicada em bancos cujo schema nao recebeu
as colunas/constraints correspondentes. Esta revisao garante o estado esperado.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261022190000"
down_revision: str | Sequence[str] | None = "20261022180000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


UPGRADE = (
    "ALTER TABLE public.estoque "
    "DROP CONSTRAINT IF EXISTS chk_estoque_quantidade_nao_negativa",
    "ALTER TABLE public.movimentacao_estoque "
    "DROP CONSTRAINT IF EXISTS chk_movimentacao_estoque_saldos_nao_negativos",
    "ALTER TABLE public.movimentacao_estoque ADD COLUMN IF NOT EXISTS id_lote uuid",
    "ALTER TABLE public.movimentacao_estoque ADD COLUMN IF NOT EXISTS origem_importacao text",
    "ALTER TABLE public.movimentacao_estoque ADD COLUMN IF NOT EXISTS id_origem_importacao text",
    """
    ALTER TABLE public.movimentacao_estoque
        ADD COLUMN IF NOT EXISTS custo_unitario numeric(12, 2)
    """,
    "ALTER TABLE public.movimentacao_estoque ADD COLUMN IF NOT EXISTS nota_fiscal text",
    "ALTER TABLE public.movimentacao_estoque ADD COLUMN IF NOT EXISTS fornecedor text",
    "ALTER TABLE public.movimentacao_estoque ADD COLUMN IF NOT EXISTS id_loja_destino uuid",
    "ALTER TABLE public.movimentacao_estoque "
    "ADD COLUMN IF NOT EXISTS dados_origem jsonb NOT NULL DEFAULT '{}'::jsonb",
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'fk_movimentacao_estoque_lote_importacao'
              AND conrelid = 'public.movimentacao_estoque'::regclass
        ) THEN
            ALTER TABLE public.movimentacao_estoque
                ADD CONSTRAINT fk_movimentacao_estoque_lote_importacao
                FOREIGN KEY (id_lote) REFERENCES public.importacao_lote (id_lote)
                ON UPDATE CASCADE ON DELETE RESTRICT;
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'fk_movimentacao_estoque_loja_destino'
              AND conrelid = 'public.movimentacao_estoque'::regclass
        ) THEN
            ALTER TABLE public.movimentacao_estoque
                ADD CONSTRAINT fk_movimentacao_estoque_loja_destino
                FOREIGN KEY (id_loja_destino) REFERENCES public.loja (id_loja)
                ON UPDATE CASCADE ON DELETE RESTRICT;
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'uq_movimentacao_estoque_origem'
              AND conrelid = 'public.movimentacao_estoque'::regclass
        ) THEN
            ALTER TABLE public.movimentacao_estoque
                ADD CONSTRAINT uq_movimentacao_estoque_origem
                UNIQUE (origem_importacao, id_origem_importacao);
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'chk_movimentacao_estoque_origem_preenchida'
              AND conrelid = 'public.movimentacao_estoque'::regclass
        ) THEN
            ALTER TABLE public.movimentacao_estoque
                ADD CONSTRAINT chk_movimentacao_estoque_origem_preenchida
                CHECK ((origem_importacao IS NULL) = (id_origem_importacao IS NULL));
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'chk_movimentacao_estoque_custo_nao_negativo'
              AND conrelid = 'public.movimentacao_estoque'::regclass
        ) THEN
            ALTER TABLE public.movimentacao_estoque
                ADD CONSTRAINT chk_movimentacao_estoque_custo_nao_negativo
                CHECK (custo_unitario IS NULL OR custo_unitario >= 0);
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'chk_movimentacao_estoque_dados_origem_objeto'
              AND conrelid = 'public.movimentacao_estoque'::regclass
        ) THEN
            ALTER TABLE public.movimentacao_estoque
                ADD CONSTRAINT chk_movimentacao_estoque_dados_origem_objeto
                CHECK (jsonb_typeof(dados_origem) = 'object');
        END IF;
    END $$
    """,
)


def upgrade() -> None:
    for comando in UPGRADE:
        op.execute(comando)


def downgrade() -> None:
    # Reverter para uma revisao que ja representa este schema seria enganoso.
    pass
