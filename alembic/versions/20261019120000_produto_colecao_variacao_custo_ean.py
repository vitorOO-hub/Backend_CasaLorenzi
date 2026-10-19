"""catalogo Vulto: custo e ean na variacao, descricao do produto vira colecao

Revision ID: 20261019120000
Revises: 20261014120000
Create Date: 2026-10-19 12:00:00

- `variacao_produto.custo` (numeric 12,2) e `variacao_produto.ean` (text), os dois aceitam vazio.
- EAN unico entre as variacoes que tem EAN (indice parcial). Vazio pode repetir.
- `produto.descricao` passa a se chamar `colecao` (nome da colecao da planilha, ex.: "verao 26").
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261019120000"
down_revision: str | Sequence[str] | None = "20261014120000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE public.variacao_produto
            ADD COLUMN IF NOT EXISTS custo numeric(12, 2) NULL,
            ADD COLUMN IF NOT EXISTS ean text NULL
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_variacao_produto_ean "
        "ON public.variacao_produto (ean) WHERE ean IS NOT NULL"
    )
    op.execute("ALTER TABLE public.produto RENAME COLUMN descricao TO colecao")


def downgrade() -> None:
    op.execute("ALTER TABLE public.produto RENAME COLUMN colecao TO descricao")
    op.execute("DROP INDEX IF EXISTS public.uq_variacao_produto_ean")
    op.execute(
        """
        ALTER TABLE public.variacao_produto
            DROP COLUMN IF EXISTS ean,
            DROP COLUMN IF EXISTS custo
        """
    )
