"""produto.id_unidade: liga o produto a unidade da marca (vulto ou casa lorenzi)

Revision ID: 20261020130000
Revises: 20261020120000
Create Date: 2026-10-20 13:00:00

- `produto.id_unidade` (aceita vazio) aponta para `unidade`.
- Os produtos existentes ficam ligados a unidade generica da marca: marca Vulto -> unidade
  "vulto" e marca Casa Lorenzi -> unidade "casa lorenzi". Produto de uma loja especifica
  passa a apontar para a unidade da loja.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261020130000"
down_revision: str | Sequence[str] | None = "20261020120000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE public.produto ADD COLUMN IF NOT EXISTS id_unidade UUID")
    op.execute(
        """
        ALTER TABLE public.produto
            ADD CONSTRAINT fk_produto_unidade
            FOREIGN KEY (id_unidade) REFERENCES public.unidade (id_unidade)
            ON UPDATE CASCADE ON DELETE RESTRICT
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_produto_id_unidade ON public.produto (id_unidade)")
    op.execute(
        """
        UPDATE public.produto p
        SET id_unidade = u.id_unidade
        FROM public.unidade u
        WHERE p.id_unidade IS NULL AND u.nome = lower(p.marca)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.idx_produto_id_unidade")
    op.execute("ALTER TABLE public.produto DROP CONSTRAINT IF EXISTS fk_produto_unidade")
    op.execute("ALTER TABLE public.produto DROP COLUMN IF EXISTS id_unidade")
