"""e-commerce unificado: venda nova do site ou app da vulto vai para o e-commerce casa lorenzi

Revision ID: 20261022160000
Revises: 20261021150000
Create Date: 2026-10-22 16:00:00

- Com a fusao das marcas o site e um so. Pedido NOVO que cairia em `vulto e-commerce`
  (LOJA-VULTO-E-COMMERCE) ou `vulto app` (LOJA-VULTO-APP) passa a ser do `E-commerce Casa Lorenzi`
  (E-COMMERCE-CASA-LORENZI). Pedido de loja fisica nao muda.
- O que ja esta gravado (compras, resgates e cadastros de antes da fusao) nao e alterado: a troca
  e feita num trigger BEFORE INSERT em `pedido`, entao so vale para linhas novas.
- `public.loja_de_venda(id_loja)` devolve a loja que recebe a venda; o checkout usa a mesma funcao
  para baixar o estoque da loja certa.
- A loja E-COMMERCE-CASA-LORENZI e criada se ainda nao existir (em producao ela ja foi criada).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261022160000"
down_revision: str | Sequence[str] | None = "20261021150000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SUBIDA = (
    """
    INSERT INTO public.loja (codigo, nome)
    VALUES ('E-COMMERCE-CASA-LORENZI', 'E-commerce Casa Lorenzi')
    ON CONFLICT (codigo) DO NOTHING
    """,
    """
    CREATE OR REPLACE FUNCTION public.loja_de_venda(p_loja uuid)
    RETURNS uuid
    LANGUAGE sql
    STABLE
    SET search_path = public, pg_temp
    AS $fn$
        SELECT COALESCE(
            (SELECT destino.id_loja
             FROM public.loja origem
             JOIN public.loja destino ON destino.codigo = 'E-COMMERCE-CASA-LORENZI'
             WHERE origem.id_loja = p_loja
               AND origem.codigo IN ('LOJA-VULTO-E-COMMERCE', 'LOJA-VULTO-APP')),
            p_loja
        )
    $fn$
    """,
    """
    CREATE OR REPLACE FUNCTION public.pedido_na_loja_de_venda()
    RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = public, pg_temp
    AS $fn$
    BEGIN
        NEW.id_loja := public.loja_de_venda(NEW.id_loja);
        RETURN NEW;
    END
    $fn$
    """,
    "DROP TRIGGER IF EXISTS trg_pedido_na_loja_de_venda ON public.pedido",
    """
    CREATE TRIGGER trg_pedido_na_loja_de_venda
    BEFORE INSERT ON public.pedido
    FOR EACH ROW EXECUTE FUNCTION public.pedido_na_loja_de_venda()
    """,
)

DESCIDA = (
    "DROP TRIGGER IF EXISTS trg_pedido_na_loja_de_venda ON public.pedido",
    "DROP FUNCTION IF EXISTS public.pedido_na_loja_de_venda()",
    "DROP FUNCTION IF EXISTS public.loja_de_venda(uuid)",
)


def upgrade() -> None:
    for comando in SUBIDA:
        op.execute(comando)


def downgrade() -> None:
    # A loja E-COMMERCE-CASA-LORENZI fica: ela pode ter sido criada a mao e ter pedidos.
    for comando in DESCIDA:
        op.execute(comando)
