"""Imagens do catalogo administradas com Supabase Storage.

Revision ID: 20261027100000
Revises: 20261024120000
Create Date: 2026-10-27 10:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261027100000"
down_revision: str | Sequence[str] | None = "20261024120000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE public.produto
        DROP CONSTRAINT IF EXISTS chk_produto_detalhes_completos
        """
    )
    op.execute(
        """
        ALTER TABLE public.produto
        ADD CONSTRAINT chk_produto_detalhes_completos CHECK (
            imagem_url IS NULL
            OR (
                length(trim(coalesce(imagem_alt, ''))) > 0
                AND (
                    lower(trim(coalesce(marca, ''))) = 'vulto'
                    OR (
                        length(trim(coalesce(tipo, ''))) > 0
                        AND length(trim(coalesce(tecido, ''))) > 0
                        AND length(trim(coalesce(tecelagem, ''))) > 0
                        AND length(trim(coalesce(costurado_em, ''))) > 0
                        AND length(trim(coalesce(nota, ''))) > 0
                        AND jsonb_typeof(cores) = 'array'
                        AND jsonb_array_length(cores) > 0
                    )
                )
            )
        )
        """
    )
    op.execute(
        """
        DO $migration$
        BEGIN
            -- O Postgres local dos testes nao instala o schema gerenciado de Storage do Supabase.
            IF to_regclass('storage.buckets') IS NULL OR to_regclass('storage.objects') IS NULL THEN
                RETURN;
            END IF;

            EXECUTE 'DROP POLICY IF EXISTS "catalogo fotos admin envia" ON storage.objects';
            EXECUTE 'DROP POLICY IF EXISTS "catalogo fotos admin remove" ON storage.objects';
            EXECUTE $policy$
                CREATE POLICY "catalogo fotos admin envia" ON storage.objects
                FOR INSERT TO authenticated
                WITH CHECK (
                    bucket_id = 'catalogo-produtos'
                    AND (SELECT public.app_papel()) = 'admin'
                )
            $policy$;
            EXECUTE $policy$
                CREATE POLICY "catalogo fotos admin remove" ON storage.objects
                FOR DELETE TO authenticated
                USING (
                    bucket_id = 'catalogo-produtos'
                    AND (SELECT public.app_papel()) = 'admin'
                )
            $policy$;
        END
        $migration$
        """
    )


def downgrade() -> None:
    # Mantem a compatibilidade com fotos sem ficha editorial para nao invalidar dados ja gravados.
    op.execute(
        """
        DO $migration$
        BEGIN
            IF to_regclass('storage.objects') IS NULL THEN
                RETURN;
            END IF;
            EXECUTE 'DROP POLICY IF EXISTS "catalogo fotos admin envia" ON storage.objects';
            EXECUTE 'DROP POLICY IF EXISTS "catalogo fotos admin remove" ON storage.objects';
        END
        $migration$
        """
    )
