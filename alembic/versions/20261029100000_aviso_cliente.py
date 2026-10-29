"""avisos por e-mail ao cliente (resumo da compra e categoria Lorenzi+) enviados pelo n8n

- `aviso_cliente`: cada aviso sai uma vez por cliente, tipo e chave (o pedido, ou a categoria e o
  ano). Guarda o estado do envio para tentar de novo quem falhou, sem nunca mandar em dobro:
  `pendente` (reservado, envio em curso), `enviado` ou `falhou` (com o erro curto e as tentativas).
  O aviso de pontos a vencer continua em `aviso_pontos` (um por lote).

RLS ligado e forcado sem policies: so o FastAPI (que ignora RLS) le e grava.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261029100000"
down_revision: str | Sequence[str] | None = "20261028140000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SUBIDA = (
    """
    CREATE TABLE IF NOT EXISTS public.aviso_cliente (
        id_aviso UUID NOT NULL DEFAULT gen_random_uuid(),
        id_usuario UUID NOT NULL,
        tipo TEXT NOT NULL,
        chave TEXT NOT NULL,
        canal TEXT NOT NULL DEFAULT 'email',
        status TEXT NOT NULL DEFAULT 'pendente',
        tentativas INTEGER NOT NULL DEFAULT 0,
        ultimo_erro TEXT,
        criado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
        atualizado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
        enviado_em TIMESTAMPTZ,
        CONSTRAINT pk_aviso_cliente PRIMARY KEY (id_aviso),
        CONSTRAINT fk_aviso_cliente_usuario FOREIGN KEY (id_usuario)
            REFERENCES public.usuario (id_usuario) ON UPDATE CASCADE ON DELETE CASCADE,
        CONSTRAINT uq_aviso_cliente UNIQUE (id_usuario, tipo, chave, canal),
        CONSTRAINT chk_aviso_cliente_tipo CHECK (tipo IN ('pos_compra', 'categoria')),
        CONSTRAINT chk_aviso_cliente_canal CHECK (canal IN ('email', 'whatsapp')),
        CONSTRAINT chk_aviso_cliente_status CHECK (status IN ('pendente', 'enviado', 'falhou')),
        CONSTRAINT chk_aviso_cliente_tentativas CHECK (tentativas >= 0)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_aviso_cliente_reenvio ON public.aviso_cliente (status, tipo) "
    "WHERE status <> 'enviado'",
    "ALTER TABLE public.aviso_cliente ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.aviso_cliente FORCE ROW LEVEL SECURITY",
    "REVOKE ALL ON public.aviso_cliente FROM anon, authenticated",
)

DESCIDA = ("DROP TABLE IF EXISTS public.aviso_cliente",)


def upgrade() -> None:
    for comando in SUBIDA:
        op.execute(comando)


def downgrade() -> None:
    for comando in DESCIDA:
        op.execute(comando)
