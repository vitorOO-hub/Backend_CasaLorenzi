"""permite saldo negativo e rastreia movimentos historicos importados

Revision ID: 20261022180000
Revises: 20261022170000
Create Date: 2026-10-22 18:00:00

O legado aprovado contem saldos negativos de estoque. Movimentos importados guardam
referencia e campos de origem sem alterar o fluxo normal de venda da aplicacao.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261022180000"
down_revision: str | Sequence[str] | None = "20261022170000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SUBIDA = (
    "ALTER TABLE public.estoque "
    "DROP CONSTRAINT IF EXISTS chk_estoque_quantidade_nao_negativa",
    "ALTER TABLE public.movimentacao_estoque "
    "DROP CONSTRAINT IF EXISTS chk_movimentacao_estoque_saldos_nao_negativos",
    """
    ALTER TABLE public.movimentacao_estoque
        ADD COLUMN id_lote uuid,
        ADD COLUMN origem_importacao text,
        ADD COLUMN id_origem_importacao text,
        ADD COLUMN custo_unitario numeric(12, 2),
        ADD COLUMN nota_fiscal text,
        ADD COLUMN fornecedor text,
        ADD COLUMN id_loja_destino uuid,
        ADD COLUMN dados_origem jsonb NOT NULL DEFAULT '{}'::jsonb,
        ADD CONSTRAINT fk_movimentacao_estoque_lote_importacao
            FOREIGN KEY (id_lote)
            REFERENCES public.importacao_lote (id_lote)
            ON UPDATE CASCADE ON DELETE RESTRICT,
        ADD CONSTRAINT fk_movimentacao_estoque_loja_destino
            FOREIGN KEY (id_loja_destino)
            REFERENCES public.loja (id_loja)
            ON UPDATE CASCADE ON DELETE RESTRICT,
        ADD CONSTRAINT uq_movimentacao_estoque_origem
            UNIQUE (origem_importacao, id_origem_importacao),
        ADD CONSTRAINT chk_movimentacao_estoque_origem_preenchida
            CHECK ((origem_importacao IS NULL) = (id_origem_importacao IS NULL)),
        ADD CONSTRAINT chk_movimentacao_estoque_custo_nao_negativo
            CHECK (custo_unitario IS NULL OR custo_unitario >= 0),
        ADD CONSTRAINT chk_movimentacao_estoque_dados_origem_objeto
            CHECK (jsonb_typeof(dados_origem) = 'object')
    """,
)

DESCIDA = (
    """
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM public.estoque WHERE quantidade < 0
        ) OR EXISTS (
            SELECT 1 FROM public.movimentacao_estoque
            WHERE quantidade_anterior < 0 OR quantidade_posterior < 0
        ) OR EXISTS (
            SELECT 1 FROM public.movimentacao_estoque
            WHERE origem_importacao IS NOT NULL
        ) THEN
            RAISE EXCEPTION
                'Downgrade bloqueado: ha saldos negativos ou movimentos Vulto importados.';
        END IF;
    END $$
    """,
    """
    ALTER TABLE public.estoque
        ADD CONSTRAINT chk_estoque_quantidade_nao_negativa CHECK (quantidade >= 0)
    """,
    """
    ALTER TABLE public.movimentacao_estoque
        ADD CONSTRAINT chk_movimentacao_estoque_saldos_nao_negativos CHECK (
            quantidade_anterior >= 0 AND quantidade_posterior >= 0
        )
    """,
    """
    ALTER TABLE public.movimentacao_estoque
        DROP CONSTRAINT chk_movimentacao_estoque_custo_nao_negativo,
        DROP CONSTRAINT chk_movimentacao_estoque_dados_origem_objeto,
        DROP CONSTRAINT chk_movimentacao_estoque_origem_preenchida,
        DROP CONSTRAINT uq_movimentacao_estoque_origem,
        DROP CONSTRAINT fk_movimentacao_estoque_loja_destino,
        DROP CONSTRAINT fk_movimentacao_estoque_lote_importacao,
        DROP COLUMN id_loja_destino,
        DROP COLUMN fornecedor,
        DROP COLUMN nota_fiscal,
        DROP COLUMN custo_unitario,
        DROP COLUMN dados_origem,
        DROP COLUMN id_origem_importacao,
        DROP COLUMN origem_importacao,
        DROP COLUMN id_lote
    """,
)


def upgrade() -> None:
    for comando in SUBIDA:
        op.execute(comando)


def downgrade() -> None:
    for comando in DESCIDA:
        op.execute(comando)
