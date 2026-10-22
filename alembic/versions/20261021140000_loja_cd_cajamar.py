"""loja: copia a unidade cd cajamar (id 7 do legado da Vulto)

Revision ID: 20261021140000
Revises: 20261021130000
Create Date: 2026-10-21 14:00:00

Mesmo padrao da 20261021120000: a linha de `loja` usa o mesmo uuid da unidade, e `unidade` nao
muda. Com isso as 7 lojas do legado da Vulto (1 pinheiros, 2 shopping eldorado, 3 savassi,
4 batel, 5 e-commerce, 6 app, 7 cd cajamar) existem em `loja`.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261021140000"
down_revision: str | Sequence[str] | None = "20261021130000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO public.loja (id_loja, codigo, nome, cidade)
        SELECT u.id_unidade,
               'LOJA-' || upper(regexp_replace(u.nome, '[^a-zA-Z0-9]+', '-', 'g')),
               u.nome,
               u.cidade
        FROM public.unidade u
        WHERE u.nome = 'cd cajamar'
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM public.loja l
        USING public.unidade u
        WHERE l.id_loja = u.id_unidade AND u.nome = 'cd cajamar'
        """
    )
