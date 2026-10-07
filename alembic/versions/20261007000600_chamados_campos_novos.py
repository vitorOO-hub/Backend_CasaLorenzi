"""campos novos da area de chamados: protocolo, cidade do cliente e anexos

Revision ID: 20261007000600
Revises: 20261007000500
Create Date: 2026-10-07 00:06:00

- atendimento.protocolo (AT-AAAA-NNNN): unico, gerado por trigger no INSERT, entao o
  POST /atendimentos antigo continua funcionando sem enviar nada. Os chamados que ja existem
  recebem protocolo na ordem de abertura.
- usuario.cidade: exibida na ficha do cliente (opcional).
- chamado_anexo: arquivos de um chamado (so o caminho no Storage). RLS forcado, leitura somente
  para quem enxerga o atendimento; a escrita e sempre pela API.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261007000600"
down_revision: str | Sequence[str] | None = "20261007000500"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLITICA_ANEXO = "chamado_anexo - leitura por quem ve o atendimento"

SUBIDA = (
    # ---- protocolo ----
    "CREATE SEQUENCE IF NOT EXISTS public.seq_protocolo_atendimento",
    "ALTER TABLE public.atendimento ADD COLUMN IF NOT EXISTS protocolo TEXT",
    """
    UPDATE public.atendimento a
    SET protocolo = 'AT-' || to_char(a.aberto_em, 'YYYY') || '-' || lpad(n.numero::text, 4, '0')
    FROM (
        SELECT id_atendimento,
               nextval('public.seq_protocolo_atendimento') AS numero
        FROM (
            SELECT id_atendimento FROM public.atendimento
            WHERE protocolo IS NULL
            ORDER BY aberto_em, id_atendimento
        ) pendentes
    ) n
    WHERE a.id_atendimento = n.id_atendimento
    """,
    """
    CREATE OR REPLACE FUNCTION public.definir_protocolo_atendimento()
    RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = public, pg_temp
    AS $fn$
    BEGIN
        IF NEW.protocolo IS NULL OR btrim(NEW.protocolo) = '' THEN
            NEW.protocolo := 'AT-' || to_char(COALESCE(NEW.aberto_em, now()), 'YYYY') || '-'
                || lpad(nextval('public.seq_protocolo_atendimento')::text, 4, '0');
        END IF;
        RETURN NEW;
    END
    $fn$
    """,
    "DROP TRIGGER IF EXISTS trg_atendimento_definir_protocolo ON public.atendimento",
    """
    CREATE TRIGGER trg_atendimento_definir_protocolo
    BEFORE INSERT ON public.atendimento
    FOR EACH ROW EXECUTE FUNCTION public.definir_protocolo_atendimento()
    """,
    "ALTER TABLE public.atendimento ALTER COLUMN protocolo SET NOT NULL",
    """
    DO $bloco$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_atendimento_protocolo') THEN
            ALTER TABLE public.atendimento
                ADD CONSTRAINT uq_atendimento_protocolo UNIQUE (protocolo);
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_atendimento_protocolo') THEN
            ALTER TABLE public.atendimento
                ADD CONSTRAINT chk_atendimento_protocolo CHECK (length(btrim(protocolo)) > 0);
        END IF;
    END
    $bloco$
    """,
    # ---- cidade do cliente ----
    "ALTER TABLE public.usuario ADD COLUMN IF NOT EXISTS cidade TEXT",
    """
    DO $bloco$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_usuario_cidade') THEN
            ALTER TABLE public.usuario
                ADD CONSTRAINT chk_usuario_cidade
                CHECK (cidade IS NULL OR length(btrim(cidade)) BETWEEN 1 AND 120);
        END IF;
    END
    $bloco$
    """,
    # ---- anexos ----
    """
    CREATE TABLE IF NOT EXISTS public.chamado_anexo (
        id_anexo UUID NOT NULL DEFAULT gen_random_uuid(),
        id_atendimento UUID NOT NULL,
        id_mensagem UUID,
        nome TEXT NOT NULL,
        caminho TEXT NOT NULL,
        tipo_conteudo TEXT,
        tamanho_bytes BIGINT,
        criado_em TIMESTAMPTZ NOT NULL DEFAULT now(),

        CONSTRAINT pk_chamado_anexo PRIMARY KEY (id_anexo),
        CONSTRAINT fk_chamado_anexo_atendimento FOREIGN KEY (id_atendimento)
            REFERENCES public.atendimento (id_atendimento) ON UPDATE CASCADE ON DELETE CASCADE,
        CONSTRAINT fk_chamado_anexo_mensagem FOREIGN KEY (id_mensagem)
            REFERENCES public.mensagem (id_mensagem) ON UPDATE CASCADE ON DELETE SET NULL,
        CONSTRAINT chk_chamado_anexo_nome CHECK (length(btrim(nome)) BETWEEN 1 AND 255),
        CONSTRAINT chk_chamado_anexo_caminho CHECK (length(btrim(caminho)) BETWEEN 1 AND 500),
        CONSTRAINT chk_chamado_anexo_tamanho CHECK (tamanho_bytes IS NULL OR tamanho_bytes >= 0)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_chamado_anexo_atendimento "
    "ON public.chamado_anexo (id_atendimento, criado_em)",
    "ALTER TABLE public.chamado_anexo ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.chamado_anexo FORCE ROW LEVEL SECURITY",
    "REVOKE ALL ON public.chamado_anexo FROM anon, authenticated",
    "GRANT SELECT ON public.chamado_anexo TO authenticated",
    f'DROP POLICY IF EXISTS "{POLITICA_ANEXO}" ON public.chamado_anexo',
    f'CREATE POLICY "{POLITICA_ANEXO}" ON public.chamado_anexo '
    "FOR SELECT TO authenticated USING (public.app_pode_ver_atendimento(id_atendimento))",
)

DESCIDA = (
    f'DROP POLICY IF EXISTS "{POLITICA_ANEXO}" ON public.chamado_anexo',
    "DROP TABLE IF EXISTS public.chamado_anexo",
    "ALTER TABLE public.usuario DROP CONSTRAINT IF EXISTS chk_usuario_cidade",
    "ALTER TABLE public.usuario DROP COLUMN IF EXISTS cidade",
    "DROP TRIGGER IF EXISTS trg_atendimento_definir_protocolo ON public.atendimento",
    "DROP FUNCTION IF EXISTS public.definir_protocolo_atendimento()",
    "ALTER TABLE public.atendimento DROP CONSTRAINT IF EXISTS chk_atendimento_protocolo",
    "ALTER TABLE public.atendimento DROP CONSTRAINT IF EXISTS uq_atendimento_protocolo",
    "ALTER TABLE public.atendimento DROP COLUMN IF EXISTS protocolo",
    "DROP SEQUENCE IF EXISTS public.seq_protocolo_atendimento",
)


def upgrade() -> None:
    for comando in SUBIDA:
        op.execute(comando)


def downgrade() -> None:
    for comando in DESCIDA:
        op.execute(comando)
