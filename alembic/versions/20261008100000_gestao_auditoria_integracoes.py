"""gestao do admin: auditoria e integracao com o ERP

Revision ID: 20261008100000
Revises: 20261007210000
Create Date: 2026-10-08 10:00:00

- `auditoria`: quem fez o que (aprovou ajuste, definiu minimo, mexeu em usuario ou no catalogo...).
  O nome do autor fica gravado junto (copia) para o registro continuar legivel se a conta mudar.
- `importacao_lote` e `importacao_registro`: lotes recebidos do ERP (Vulto) e os registros que ainda
  precisam de um SKU da Casa Lorenzi.

As tres tabelas ficam FECHADAS ao front (RLS ligado e forcado, sem nenhum privilegio para anon ou
authenticated): so a API le e grava, e so para o administrador.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261008100000"
down_revision: str | Sequence[str] | None = "20261007210000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABELAS = ("auditoria", "importacao_lote", "importacao_registro")

SUBIDA = (
    """
    CREATE TABLE IF NOT EXISTS public.auditoria (
        id_auditoria UUID NOT NULL DEFAULT gen_random_uuid(),
        criada_em TIMESTAMPTZ NOT NULL DEFAULT now(),
        id_usuario UUID,
        autor_nome TEXT NOT NULL,
        acao TEXT NOT NULL,
        detalhe TEXT NOT NULL DEFAULT '',

        CONSTRAINT pk_auditoria PRIMARY KEY (id_auditoria),
        CONSTRAINT fk_auditoria_usuario FOREIGN KEY (id_usuario)
            REFERENCES public.usuario (id_usuario) ON UPDATE CASCADE ON DELETE SET NULL,
        CONSTRAINT chk_auditoria_textos CHECK (
            length(btrim(autor_nome)) > 0 AND length(btrim(acao)) BETWEEN 1 AND 120
            AND length(detalhe) <= 500)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_auditoria_criada_em ON public.auditoria (criada_em DESC)",
    """
    CREATE TABLE IF NOT EXISTS public.importacao_lote (
        id_lote UUID NOT NULL DEFAULT gen_random_uuid(),
        codigo TEXT NOT NULL,
        origem TEXT NOT NULL DEFAULT 'Vulto',
        recebido_em TIMESTAMPTZ NOT NULL DEFAULT now(),
        com_erro BOOLEAN NOT NULL DEFAULT FALSE,

        CONSTRAINT pk_importacao_lote PRIMARY KEY (id_lote),
        CONSTRAINT uq_importacao_lote_codigo UNIQUE (codigo),
        CONSTRAINT chk_importacao_lote_textos CHECK (
            length(btrim(codigo)) BETWEEN 1 AND 60 AND length(btrim(origem)) BETWEEN 1 AND 60)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS public.importacao_registro (
        id_registro UUID NOT NULL DEFAULT gen_random_uuid(),
        id_lote UUID NOT NULL,
        descricao_externa TEXT NOT NULL,
        codigo_externo TEXT NOT NULL,
        id_variacao UUID,
        mapeado_em TIMESTAMPTZ,
        id_usuario_mapeou UUID,

        CONSTRAINT pk_importacao_registro PRIMARY KEY (id_registro),
        CONSTRAINT fk_importacao_registro_lote FOREIGN KEY (id_lote)
            REFERENCES public.importacao_lote (id_lote) ON UPDATE CASCADE ON DELETE CASCADE,
        CONSTRAINT fk_importacao_registro_variacao FOREIGN KEY (id_variacao)
            REFERENCES public.variacao_produto (id_variacao) ON UPDATE CASCADE ON DELETE SET NULL,
        CONSTRAINT fk_importacao_registro_usuario FOREIGN KEY (id_usuario_mapeou)
            REFERENCES public.usuario (id_usuario) ON UPDATE CASCADE ON DELETE SET NULL,
        CONSTRAINT uq_importacao_registro_lote_codigo UNIQUE (id_lote, codigo_externo),
        CONSTRAINT chk_importacao_registro_textos CHECK (
            length(btrim(descricao_externa)) BETWEEN 1 AND 300
            AND length(btrim(codigo_externo)) BETWEEN 1 AND 80)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_importacao_registro_lote "
    "ON public.importacao_registro (id_lote)",
    "CREATE INDEX IF NOT EXISTS idx_importacao_registro_pendente "
    "ON public.importacao_registro (codigo_externo) WHERE id_variacao IS NULL",
    *(
        comando
        for tabela in TABELAS
        for comando in (
            f"ALTER TABLE public.{tabela} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE public.{tabela} FORCE ROW LEVEL SECURITY",
            f"REVOKE ALL ON public.{tabela} FROM anon, authenticated",
        )
    ),
)

DESCIDA = tuple(f"DROP TABLE IF EXISTS public.{tabela}" for tabela in reversed(TABELAS))


def upgrade() -> None:
    for comando in SUBIDA:
        op.execute(comando)


def downgrade() -> None:
    for comando in DESCIDA:
        op.execute(comando)
