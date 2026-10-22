"""fila de vendas pendentes: justificativa do descarte; venda antiga fica na loja de origem

Revision ID: 20261024110000
Revises: 20261024100000
Create Date: 2026-10-24 11:00:00

- `venda_importacao_pendente.observacao_resolucao`: o porque de quem resolveu a pendencia pela
  tela da fila (obrigatoria para descartar; a API exige).
- O trigger do e-commerce unificado (20261022160000) passa a redirecionar so venda feita depois da
  fusao: venda antiga da Vulto resolvida pela fila continua em `vulto app` ou `vulto e-commerce`,
  como as que a importacao ja gravou. Compra nova do site ou app segue para o E-commerce Casa
  Lorenzi como antes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261024110000"
down_revision: str | Sequence[str] | None = "20261024100000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUSAO = "2026-10-22 00:00:00-03"


def _trigger(condicao: str) -> str:
    return f"""
    CREATE OR REPLACE FUNCTION public.pedido_na_loja_de_venda()
    RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = public, pg_temp
    AS $fn$
    BEGIN
        {condicao}
        RETURN NEW;
    END
    $fn$
    """


def upgrade() -> None:
    op.execute(
        "ALTER TABLE public.venda_importacao_pendente "
        "ADD COLUMN IF NOT EXISTS observacao_resolucao TEXT"
    )
    op.execute(
        _trigger(
            f"IF NEW.criado_em IS NULL OR NEW.criado_em >= TIMESTAMPTZ '{FUSAO}' THEN\n"
            "            NEW.id_loja := public.loja_de_venda(NEW.id_loja);\n"
            "        END IF;"
        )
    )


def downgrade() -> None:
    op.execute(_trigger("NEW.id_loja := public.loja_de_venda(NEW.id_loja);"))
    op.execute(
        "ALTER TABLE public.venda_importacao_pendente DROP COLUMN IF EXISTS observacao_resolucao"
    )
