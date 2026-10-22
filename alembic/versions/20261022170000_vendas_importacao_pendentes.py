"""guarda vendas do Vulto que ainda nao podem virar pedidos

Revision ID: 20261022170000
Revises: 20261022160000
Create Date: 2026-10-22 17:00:00

O payload de origem pode conter identificadores pessoais. A tabela fica inacessivel ao
frontend; somente a API, com autorizacao administrativa, pode consultar os dados necessarios.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261022170000"
down_revision: str | Sequence[str] | None = "20261022160000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SUBIDA = (
    """
    CREATE TABLE public.venda_importacao_pendente (
        id_venda_pendente UUID NOT NULL DEFAULT gen_random_uuid(),
        id_lote UUID NOT NULL,
        origem TEXT NOT NULL DEFAULT 'vulto',
        venda_id_origem TEXT NOT NULL,
        status_origem TEXT,
        estado TEXT NOT NULL DEFAULT 'pendente',
        motivos TEXT[] NOT NULL,
        quantidade_itens INTEGER NOT NULL DEFAULT 0,
        dados_origem JSONB NOT NULL,
        id_pedido UUID,
        id_usuario_resolveu UUID,
        resolvida_em TIMESTAMPTZ,
        criada_em TIMESTAMPTZ NOT NULL DEFAULT now(),
        atualizada_em TIMESTAMPTZ NOT NULL DEFAULT now(),

        CONSTRAINT pk_venda_importacao_pendente PRIMARY KEY (id_venda_pendente),
        CONSTRAINT fk_venda_importacao_pendente_lote FOREIGN KEY (id_lote)
            REFERENCES public.importacao_lote (id_lote) ON UPDATE CASCADE ON DELETE RESTRICT,
        CONSTRAINT fk_venda_importacao_pendente_pedido FOREIGN KEY (id_pedido)
            REFERENCES public.pedido (id_pedido) ON UPDATE CASCADE ON DELETE RESTRICT,
        CONSTRAINT fk_venda_importacao_pendente_usuario FOREIGN KEY (id_usuario_resolveu)
            REFERENCES public.usuario (id_usuario) ON UPDATE CASCADE ON DELETE SET NULL,
        CONSTRAINT uq_venda_importacao_pendente_origem UNIQUE (origem, venda_id_origem),
        CONSTRAINT chk_venda_importacao_pendente_origem CHECK (
            length(btrim(origem)) BETWEEN 1 AND 40
            AND length(btrim(venda_id_origem)) BETWEEN 1 AND 100
        ),
        CONSTRAINT chk_venda_importacao_pendente_estado CHECK (
            estado IN ('pendente', 'importada', 'descartada')
        ),
        CONSTRAINT chk_venda_importacao_pendente_motivos CHECK (cardinality(motivos) > 0),
        CONSTRAINT chk_venda_importacao_pendente_quantidade CHECK (quantidade_itens >= 0),
        CONSTRAINT chk_venda_importacao_pendente_payload CHECK (
            jsonb_typeof(dados_origem) = 'object'
        ),
        CONSTRAINT chk_venda_importacao_pendente_resolucao CHECK (
            (estado = 'pendente' AND id_pedido IS NULL AND resolvida_em IS NULL)
            OR (estado = 'importada' AND id_pedido IS NOT NULL AND resolvida_em IS NOT NULL)
            OR (estado = 'descartada' AND id_pedido IS NULL AND resolvida_em IS NOT NULL)
        )
    )
    """,
    "CREATE INDEX idx_venda_importacao_pendente_estado_criada "
    "ON public.venda_importacao_pendente (estado, criada_em DESC)",
    "CREATE INDEX idx_venda_importacao_pendente_lote "
    "ON public.venda_importacao_pendente (id_lote)",
    "ALTER TABLE public.venda_importacao_pendente ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.venda_importacao_pendente FORCE ROW LEVEL SECURITY",
    "REVOKE ALL ON public.venda_importacao_pendente FROM PUBLIC, anon, authenticated",
)

DESCIDA = ("DROP TABLE IF EXISTS public.venda_importacao_pendente",)


def upgrade() -> None:
    for comando in SUBIDA:
        op.execute(comando)


def downgrade() -> None:
    for comando in DESCIDA:
        op.execute(comando)
