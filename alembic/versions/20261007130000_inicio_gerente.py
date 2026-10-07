"""inicio do gerente: canal e frete do pedido, ajustes de estoque a aprovar e indices

Revision ID: 20261007130000
Revises: 20261007120000
Create Date: 2026-10-07 13:00:00

O inicio do gerente mostra vendas por canal (loja fisica x online), faturamento sem frete e os
ajustes de estoque esperando aprovacao. Para isso o banco ganha:

- `pedido.canal_venda` ('loja' | 'online'): antes so dava para adivinhar pelo texto da observacao.
  O padrao e 'online' porque todo pedido criado pelo portal e online; os pedidos antigos que nao
  vieram do portal viram 'loja'.
- `pedido.valor_frete`: o frete estava solto na observacao ("Frete: R$ 49.00") e inflava o
  faturamento de produtos. Os pedidos antigos do portal tem o valor extraido do texto.
- `ajuste_estoque`: pedidos de ajuste de saldo que o gerente aprova ou rejeita. Nasce com RLS
  ligado e forcado e sem privilegio para o front: so a API (que confere papel e loja) acessa.
- Indices para as consultas por loja e periodo.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261007130000"
down_revision: str | Sequence[str] | None = "20261007120000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SUBIDA = (
    # ---- pedido: canal e frete ----
    "ALTER TABLE public.pedido ADD COLUMN IF NOT EXISTS canal_venda TEXT NOT NULL DEFAULT 'online'",
    "ALTER TABLE public.pedido ADD COLUMN IF NOT EXISTS valor_frete "
    "NUMERIC(12,2) NOT NULL DEFAULT 0",
    "ALTER TABLE public.pedido DROP CONSTRAINT IF EXISTS chk_pedido_canal_venda",
    "ALTER TABLE public.pedido ADD CONSTRAINT chk_pedido_canal_venda "
    "CHECK (canal_venda IN ('loja', 'online'))",
    "ALTER TABLE public.pedido DROP CONSTRAINT IF EXISTS chk_pedido_valor_frete_nao_negativo",
    "ALTER TABLE public.pedido ADD CONSTRAINT chk_pedido_valor_frete_nao_negativo "
    "CHECK (valor_frete >= 0)",
    # Pedidos que ja existiam: os do portal sao online e trazem o frete na observacao.
    """
    UPDATE public.pedido
    SET canal_venda = 'loja'
    WHERE observacao IS NULL OR observacao NOT LIKE 'Checkout pelo portal%'
    """,
    """
    UPDATE public.pedido
    SET valor_frete = LEAST(
        valor_total,
        replace(substring(observacao FROM 'Frete: R\\$ ?([0-9]+[.,][0-9]{2})'), ',', '.')::numeric
    )
    WHERE observacao ~ 'Frete: R\\$ ?[0-9]+[.,][0-9]{2}'
    """,
    "CREATE INDEX IF NOT EXISTS idx_pedido_loja_criado_em ON public.pedido (id_loja, criado_em)",
    "CREATE INDEX IF NOT EXISTS idx_item_pedido_id_variacao ON public.item_pedido (id_variacao)",
    # ---- ajustes de estoque a aprovar ----
    """
    CREATE TABLE IF NOT EXISTS public.ajuste_estoque (
        id_ajuste_estoque UUID NOT NULL DEFAULT gen_random_uuid(),
        id_loja UUID NOT NULL,
        id_variacao UUID NOT NULL,
        id_usuario_solicitante UUID NOT NULL,
        id_usuario_decisor UUID,
        quantidade INTEGER NOT NULL,
        motivo TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pendente',
        solicitado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
        decidido_em TIMESTAMPTZ,

        CONSTRAINT pk_ajuste_estoque PRIMARY KEY (id_ajuste_estoque),
        CONSTRAINT fk_ajuste_estoque_loja FOREIGN KEY (id_loja)
            REFERENCES public.loja (id_loja) ON UPDATE CASCADE ON DELETE RESTRICT,
        CONSTRAINT fk_ajuste_estoque_variacao FOREIGN KEY (id_variacao)
            REFERENCES public.variacao_produto (id_variacao) ON UPDATE CASCADE ON DELETE RESTRICT,
        CONSTRAINT fk_ajuste_estoque_solicitante FOREIGN KEY (id_usuario_solicitante)
            REFERENCES public.usuario (id_usuario) ON UPDATE CASCADE ON DELETE RESTRICT,
        CONSTRAINT fk_ajuste_estoque_decisor FOREIGN KEY (id_usuario_decisor)
            REFERENCES public.usuario (id_usuario) ON UPDATE CASCADE ON DELETE RESTRICT,
        CONSTRAINT chk_ajuste_estoque_quantidade CHECK (quantidade <> 0),
        CONSTRAINT chk_ajuste_estoque_motivo CHECK (length(trim(motivo)) > 0),
        CONSTRAINT chk_ajuste_estoque_status
            CHECK (status IN ('pendente', 'aprovado', 'rejeitado')),
        -- Pendente nao tem decisao; aprovado e rejeitado sempre tem quem decidiu e quando.
        CONSTRAINT chk_ajuste_estoque_decisao CHECK (
            (status = 'pendente' AND id_usuario_decisor IS NULL AND decidido_em IS NULL)
            OR (status <> 'pendente' AND id_usuario_decisor IS NOT NULL
                AND decidido_em IS NOT NULL)
        )
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ajuste_estoque_loja_status "
    "ON public.ajuste_estoque (id_loja, status)",
    "ALTER TABLE public.ajuste_estoque ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.ajuste_estoque FORCE ROW LEVEL SECURITY",
    "REVOKE ALL ON public.ajuste_estoque FROM anon, authenticated",
)

DESCIDA = (
    "DROP TABLE IF EXISTS public.ajuste_estoque",
    "DROP INDEX IF EXISTS public.idx_item_pedido_id_variacao",
    "DROP INDEX IF EXISTS public.idx_pedido_loja_criado_em",
    "ALTER TABLE public.pedido DROP CONSTRAINT IF EXISTS chk_pedido_valor_frete_nao_negativo",
    "ALTER TABLE public.pedido DROP CONSTRAINT IF EXISTS chk_pedido_canal_venda",
    "ALTER TABLE public.pedido DROP COLUMN IF EXISTS valor_frete",
    "ALTER TABLE public.pedido DROP COLUMN IF EXISTS canal_venda",
)


def upgrade() -> None:
    for comando in SUBIDA:
        op.execute(comando)


def downgrade() -> None:
    for comando in DESCIDA:
        op.execute(comando)
