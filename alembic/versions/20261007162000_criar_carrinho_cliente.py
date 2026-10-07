"""cliente: carrinho persistido

Revision ID: 20261007162000
Revises: 20261007143000
Create Date: 2026-10-07 16:20:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261007162000"
down_revision: str | Sequence[str] | None = "20261007143000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SUBIDA = (
    """
    CREATE TABLE IF NOT EXISTS public.carrinho (
        id_carrinho UUID NOT NULL DEFAULT gen_random_uuid(),
        id_cliente UUID NOT NULL,
        id_variacao UUID NOT NULL,
        quantidade INTEGER NOT NULL,
        criado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
        atualizado_em TIMESTAMPTZ NOT NULL DEFAULT now(),

        CONSTRAINT pk_carrinho PRIMARY KEY (id_carrinho),
        CONSTRAINT fk_carrinho_cliente FOREIGN KEY (id_cliente)
            REFERENCES public.usuario (id_usuario) ON UPDATE CASCADE ON DELETE CASCADE,
        CONSTRAINT fk_carrinho_variacao FOREIGN KEY (id_variacao)
            REFERENCES public.variacao_produto (id_variacao) ON UPDATE CASCADE ON DELETE CASCADE,
        CONSTRAINT uq_carrinho_cliente_variacao UNIQUE (id_cliente, id_variacao),
        CONSTRAINT chk_carrinho_quantidade CHECK (quantidade > 0 AND quantidade <= 99)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_carrinho_id_cliente ON public.carrinho (id_cliente)",
    "CREATE INDEX IF NOT EXISTS idx_carrinho_id_variacao ON public.carrinho (id_variacao)",
    "ALTER TABLE public.carrinho ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.carrinho FORCE ROW LEVEL SECURITY",
    "REVOKE ALL ON public.carrinho FROM anon, authenticated",
)

DESCIDA = (
    "DROP TABLE IF EXISTS public.carrinho",
)


def upgrade() -> None:
    for comando in SUBIDA:
        op.execute(comando)


def downgrade() -> None:
    for comando in DESCIDA:
        op.execute(comando)
