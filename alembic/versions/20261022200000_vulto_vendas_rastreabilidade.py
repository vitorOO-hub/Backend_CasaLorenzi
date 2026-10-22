"""permite importar vendas historicas sem inventar cliente ou preco por item"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261022200000"
down_revision: str | Sequence[str] | None = "20261022190000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SUBIDA = (
    "ALTER TABLE public.pedido ALTER COLUMN id_cliente DROP NOT NULL",
    "ALTER TABLE public.pedido DROP CONSTRAINT IF EXISTS chk_pedido_valor_total_nao_negativo",
    """ALTER TABLE public.pedido ADD CONSTRAINT chk_pedido_importacao_manual_cliente_nulo
       CHECK (id_cliente IS NOT NULL OR numero_pedido LIKE 'VULTO-BATEL-MANUAL-%')""",
    """ALTER TABLE public.pedido ADD CONSTRAINT chk_pedido_importacao_manual_total_negativo
       CHECK (valor_total >= 0 OR numero_pedido LIKE 'VULTO-BATEL-MANUAL-%')""",
    "ALTER TABLE public.item_pedido ALTER COLUMN preco_unitario DROP NOT NULL",
    """
    CREATE FUNCTION public.validar_preco_nulo_venda_manual()
    RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public
    AS $$
    BEGIN
        IF NEW.preco_unitario IS NULL AND NOT EXISTS (
            SELECT 1 FROM public.pedido p
            WHERE p.id_pedido = NEW.id_pedido
              AND p.numero_pedido LIKE 'VULTO-BATEL-MANUAL-%'
        ) THEN
            RAISE EXCEPTION 'preco_unitario NULL permitido somente em venda manual do Batel';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    "REVOKE ALL ON FUNCTION public.validar_preco_nulo_venda_manual() "
    "FROM PUBLIC, anon, authenticated",
    """CREATE TRIGGER trg_validar_preco_nulo_venda_manual
       BEFORE INSERT OR UPDATE OF id_pedido, preco_unitario ON public.item_pedido
       FOR EACH ROW EXECUTE FUNCTION public.validar_preco_nulo_venda_manual()""",
    """
    CREATE TABLE public.venda_importacao_origem (
        id_venda_importacao_origem UUID NOT NULL DEFAULT gen_random_uuid(),
        id_lote UUID NOT NULL,
        id_pedido UUID NOT NULL,
        origem TEXT NOT NULL,
        chave_origem TEXT NOT NULL,
        venda_id_origem TEXT,
        compra_id_origem TEXT,
        funcionario_id_origem TEXT,
        vendedor_padronizado TEXT,
        dados_origem JSONB NOT NULL,
        criada_em TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT pk_venda_importacao_origem PRIMARY KEY (id_venda_importacao_origem),
        CONSTRAINT fk_venda_importacao_origem_lote FOREIGN KEY (id_lote)
            REFERENCES public.importacao_lote (id_lote) ON UPDATE CASCADE ON DELETE RESTRICT,
        CONSTRAINT fk_venda_importacao_origem_pedido FOREIGN KEY (id_pedido)
            REFERENCES public.pedido (id_pedido) ON UPDATE CASCADE ON DELETE RESTRICT,
        CONSTRAINT uq_venda_importacao_origem_chave UNIQUE (origem, chave_origem),
        CONSTRAINT uq_venda_importacao_origem_pedido UNIQUE (id_pedido),
        CONSTRAINT chk_venda_importacao_origem_texto CHECK (
            length(btrim(origem)) BETWEEN 1 AND 80
            AND length(btrim(chave_origem)) BETWEEN 1 AND 160
        ),
        CONSTRAINT chk_venda_importacao_origem_payload CHECK (
            jsonb_typeof(dados_origem) = 'object'
        )
    )
    """,
    "CREATE INDEX idx_venda_importacao_origem_lote ON public.venda_importacao_origem (id_lote)",
    "ALTER TABLE public.venda_importacao_origem ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.venda_importacao_origem FORCE ROW LEVEL SECURITY",
    "REVOKE ALL ON public.venda_importacao_origem FROM PUBLIC, anon, authenticated",
)


def upgrade() -> None:
    for comando in SUBIDA:
        op.execute(comando)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_validar_preco_nulo_venda_manual ON public.item_pedido")
    op.execute("DROP FUNCTION IF EXISTS public.validar_preco_nulo_venda_manual()")
    op.execute("DROP TABLE IF EXISTS public.venda_importacao_origem")
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM public.pedido WHERE id_cliente IS NULL)
               OR EXISTS (SELECT 1 FROM public.item_pedido WHERE preco_unitario IS NULL)
               OR EXISTS (SELECT 1 FROM public.pedido WHERE valor_total < 0) THEN
                RAISE EXCEPTION 'Downgrade bloqueado: ha dados historicos que dependem '
                    'da migration';
            END IF;
        END $$
        """
    )
    op.execute("ALTER TABLE public.pedido ALTER COLUMN id_cliente SET NOT NULL")
    op.execute(
        "ALTER TABLE public.pedido DROP CONSTRAINT IF EXISTS "
        "chk_pedido_importacao_manual_cliente_nulo"
    )
    op.execute(
        "ALTER TABLE public.pedido DROP CONSTRAINT IF EXISTS "
        "chk_pedido_importacao_manual_total_negativo"
    )
    op.execute(
        "ALTER TABLE public.pedido ADD CONSTRAINT chk_pedido_valor_total_nao_negativo "
        "CHECK (valor_total >= 0)"
    )
    op.execute("ALTER TABLE public.item_pedido ALTER COLUMN preco_unitario SET NOT NULL")
