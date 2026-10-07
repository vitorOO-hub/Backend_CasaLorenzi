"""hook de claims do token (papel e loja_id)

Revision ID: 20261007000200
Revises: 20261007000100
Create Date: 2026-10-07 00:02:00

Custom Access Token Hook do Supabase. A ativacao no painel (Authentication > Hooks) e um
passo manual: sem ela, todo token de equipe sai sem papel.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261007000200"
down_revision: str | Sequence[str] | None = "20261007000100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SUBIDA = (
    """
    CREATE OR REPLACE FUNCTION public.hook_claims_token(event jsonb)
    RETURNS jsonb
    LANGUAGE plpgsql
    STABLE
    SECURITY DEFINER
    SET search_path = public, pg_temp
    AS $fn$
    DECLARE
        v_claims jsonb := coalesce(event -> 'claims', '{}'::jsonb);
        v_papel text;
        v_loja uuid;
    BEGIN
        SELECT
            CASE t.codigo
                WHEN 'diretor' THEN 'admin'
                WHEN 'cliente' THEN NULL
                ELSE t.codigo
            END,
            u.id_loja
        INTO v_papel, v_loja
        FROM public.usuario u
        JOIN public.tipo_usuario t ON t.id_tipo_usuario = u.id_tipo_usuario
        WHERE u.auth_user_id = (event ->> 'user_id')::uuid
          AND u.ativo
          AND t.ativo;

        -- Nunca confiar em papel ou loja que ja venham no token.
        v_claims := v_claims - 'papel' - 'loja_id';

        IF v_papel IS NOT NULL THEN
            v_claims := jsonb_set(v_claims, '{papel}', to_jsonb(v_papel));
            IF v_papel <> 'admin' AND v_loja IS NOT NULL THEN
                v_claims := jsonb_set(v_claims, '{loja_id}', to_jsonb(v_loja::text));
            END IF;
        END IF;

        RETURN jsonb_set(event, '{claims}', v_claims);
    END
    $fn$
    """,
    "REVOKE ALL ON FUNCTION public.hook_claims_token(jsonb) FROM PUBLIC, anon, authenticated",
    "GRANT EXECUTE ON FUNCTION public.hook_claims_token(jsonb) TO supabase_auth_admin",
)

DESCIDA = ("DROP FUNCTION IF EXISTS public.hook_claims_token(jsonb)",)


def upgrade() -> None:
    for comando in SUBIDA:
        op.execute(comando)


def downgrade() -> None:
    for comando in DESCIDA:
        op.execute(comando)
