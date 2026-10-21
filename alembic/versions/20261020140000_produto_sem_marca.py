"""produto sem marca: a marca passa a ser a unidade (produto.id_unidade)

Revision ID: 20261020140000
Revises: 20261021140000
Create Date: 2026-10-20 14:00:00

- Apaga `produto.marca`. A informacao ja esta em `produto.id_unidade` (unidade "vulto" ou
  "casa lorenzi" para os produtos da marca, ou a unidade da loja).
- `uq_produto_nome_marca` (nome, marca) sai junto com a coluna e entra `uq_produto_nome_unidade`
  (nome, id_unidade).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261020140000"
down_revision: str | Sequence[str] | None = "20261021140000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE public.produto "
        "ADD CONSTRAINT uq_produto_nome_unidade UNIQUE (nome, id_unidade)"
    )
    op.execute("ALTER TABLE public.produto DROP COLUMN marca")


def downgrade() -> None:
    op.execute("ALTER TABLE public.produto ADD COLUMN marca TEXT")
    op.execute(
        """
        UPDATE public.produto p
        SET marca = CASE u.nome
            WHEN 'vulto' THEN 'Vulto' WHEN 'casa lorenzi' THEN 'Casa Lorenzi'
        END
        FROM public.unidade u
        WHERE u.id_unidade = p.id_unidade
        """
    )
    op.execute("ALTER TABLE public.produto DROP CONSTRAINT uq_produto_nome_unidade")
    op.execute(
        "ALTER TABLE public.produto ADD CONSTRAINT uq_produto_nome_marca UNIQUE (nome, marca)"
    )
