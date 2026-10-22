"""tabela unidade: lojas, canais e CD de onde um produto, cliente ou pedido vem

Revision ID: 20261020120000
Revises: 20261019120000
Create Date: 2026-10-20 12:00:00

- `unidade` (id_unidade, nome, cidade) lista as unidades das duas marcas (Vulto e Casa Lorenzi),
  inclusive canais sem cidade (e-commerce, app) e o CD. Nao substitui `loja`: `loja` continua
  sendo a loja com estoque, pedido e equipe.
- Nenhuma outra tabela aponta para `unidade` ainda; cada FK entra na migration da tabela que
  passar a usar.
- RLS ligado e sem policy: so a conexao do FastAPI (que ignora RLS) le e escreve.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261020120000"
down_revision: str | Sequence[str] | None = "20261019120000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UNIDADES = (
    ("vulto pinheiros", "sao paulo"),
    ("vulto shopping eldorado", "sao paulo"),
    ("vulto savassi", "belo horizonte"),
    ("vulto batel", "curitiba"),
    ("vulto e-commerce", None),
    ("vulto app", None),
    ("cd cajamar", "cajamar"),
    ("vulto", None),
    ("casa lorenzi ibirapuera", "sao paulo"),
    ("casa lorenzi barra", "rio de janeiro"),
    ("casa lorenzi savassi", "belo horizonte"),
    ("casa lorenzi", None),
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.unidade (
            id_unidade UUID NOT NULL DEFAULT gen_random_uuid(),
            nome TEXT NOT NULL,
            cidade TEXT,

            CONSTRAINT pk_unidade PRIMARY KEY (id_unidade),
            CONSTRAINT uq_unidade_nome UNIQUE (nome),
            CONSTRAINT chk_unidade_nome_nao_vazio CHECK (length(trim(nome)) > 0),
            CONSTRAINT chk_unidade_cidade_nao_vazia
                CHECK (cidade IS NULL OR length(trim(cidade)) > 0)
        )
        """
    )
    op.execute("ALTER TABLE public.unidade ENABLE ROW LEVEL SECURITY")
    for nome, cidade in UNIDADES:
        op.execute(
            sa.text(
                "INSERT INTO public.unidade (nome, cidade) VALUES (:nome, :cidade) "
                "ON CONFLICT ON CONSTRAINT uq_unidade_nome DO NOTHING"
            ).bindparams(nome=nome, cidade=cidade)
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.unidade")
