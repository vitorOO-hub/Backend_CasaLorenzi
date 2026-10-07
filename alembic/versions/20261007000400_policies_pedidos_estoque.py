"""policies de leitura de pedidos, itens, pagamentos, estoque e movimentacoes

Revision ID: 20261007000400
Revises: 20261007000300
Create Date: 2026-10-07 00:04:00

Somente leitura. Item e pagamento herdam a visibilidade do pedido (a subconsulta passa pela
policy de pedido do proprio usuario).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261007000400"
down_revision: str | Sequence[str] | None = "20261007000300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GRANT_SELECT = (
    "GRANT SELECT ON public.pedido, public.item_pedido, public.pagamento, public.estoque, "
    "public.movimentacao_estoque, public.status_pagamento, "
    "public.tipo_movimentacao_estoque TO authenticated"
)
REVOKE_SELECT = (
    "REVOKE SELECT ON public.pedido, public.item_pedido, public.pagamento, public.estoque, "
    "public.movimentacao_estoque, public.status_pagamento, "
    "public.tipo_movimentacao_estoque FROM authenticated"
)

PAPEIS_DO_PEDIDO = "ARRAY['atendente', 'gerente_loja', 'operador_estoque']"
PAPEIS_DO_ESTOQUE = "ARRAY['operador_estoque', 'gerente_loja']"

# (nome, tabela, corpo da policy)
POLITICAS = (
    (
        "pedido - leitura por dono ou equipe da loja",
        "pedido",
        "FOR SELECT TO authenticated USING ("
        "id_cliente = (SELECT public.app_usuario_id()) "
        f"OR public.app_papel_na_loja(id_loja, {PAPEIS_DO_PEDIDO}))",
    ),
    (
        "item_pedido - leitura por quem ve o pedido",
        "item_pedido",
        "FOR SELECT TO authenticated USING (EXISTS ("
        "SELECT 1 FROM public.pedido p WHERE p.id_pedido = item_pedido.id_pedido))",
    ),
    (
        "pagamento - leitura por quem ve o pedido",
        "pagamento",
        "FOR SELECT TO authenticated USING (EXISTS ("
        "SELECT 1 FROM public.pedido p WHERE p.id_pedido = pagamento.id_pedido))",
    ),
    (
        "estoque - leitura pela equipe de estoque da loja",
        "estoque",
        "FOR SELECT TO authenticated USING ("
        f"public.app_papel_na_loja(id_loja, {PAPEIS_DO_ESTOQUE}))",
    ),
    (
        "movimentacao_estoque - leitura pela equipe de estoque da loja",
        "movimentacao_estoque",
        "FOR SELECT TO authenticated USING ("
        f"public.app_papel_na_loja(id_loja, {PAPEIS_DO_ESTOQUE}))",
    ),
    (
        "status_pagamento - leitura por usuarios logados",
        "status_pagamento",
        "FOR SELECT TO authenticated USING (ativo)",
    ),
    (
        "tipo_movimentacao_estoque - leitura por usuarios logados",
        "tipo_movimentacao_estoque",
        "FOR SELECT TO authenticated USING (ativo)",
    ),
)


def upgrade() -> None:
    op.execute(GRANT_SELECT)
    for nome, tabela, corpo in POLITICAS:
        op.execute(f'DROP POLICY IF EXISTS "{nome}" ON public.{tabela}')
        op.execute(f'CREATE POLICY "{nome}" ON public.{tabela} {corpo}')


def downgrade() -> None:
    for nome, tabela, _corpo in reversed(POLITICAS):
        op.execute(f'DROP POLICY IF EXISTS "{nome}" ON public.{tabela}')
    op.execute(REVOKE_SELECT)
