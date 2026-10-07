"""rls explicito, privilegios minimos e funcoes auxiliares das policies

Revision ID: 20261007000100
Revises: 20261007000000
Create Date: 2026-10-07 00:01:00

A API conecta como postgres (BYPASSRLS); RLS e privilegios protegem o acesso direto do front
ao Supabase (PostgREST e Realtime). O downgrade restaura o estado anterior documentado:
RLS ligado sem FORCE, anon com SELECT e authenticated com SELECT/INSERT/UPDATE/DELETE.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261007000100"
down_revision: str | Sequence[str] | None = "20261007000000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ASSINATURAS_FUNCOES = (
    "app_usuario_id()",
    "app_papel()",
    "app_loja_id()",
    "app_papel_na_loja(uuid, text[])",
    "app_pode_ver_atendimento(uuid)",
    "app_atendimento_aceita_mensagem(uuid)",
    "app_pode_avaliar_atendimento(uuid)",
)

LIGAR_RLS_EM_TODAS_AS_TABELAS = """
DO $bloco$
DECLARE
    tabela record;
BEGIN
    FOR tabela IN
        SELECT tablename FROM pg_tables
        WHERE schemaname = 'public' AND tablename <> 'alembic_version'
    LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', tabela.tablename);
        EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', tabela.tablename);
    END LOOP;
END
$bloco$
"""

DESLIGAR_FORCE_EM_TODAS_AS_TABELAS = """
DO $bloco$
DECLARE
    tabela record;
BEGIN
    FOR tabela IN
        SELECT tablename FROM pg_tables
        WHERE schemaname = 'public' AND tablename <> 'alembic_version'
    LOOP
        EXECUTE format('ALTER TABLE public.%I NO FORCE ROW LEVEL SECURITY', tabela.tablename);
    END LOOP;
END
$bloco$
"""

PRIVILEGIOS_SUBIDA = (
    "REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated",
    "ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public "
    "REVOKE ALL ON TABLES FROM anon, authenticated",
    # Catalogo publico e dados de apoio: as policies de leitura ja existem desde a migration SQL.
    "GRANT SELECT ON public.loja, public.produto, public.variacao_produto TO anon, authenticated",
    "GRANT SELECT ON public.metodo_pagamento, public.status_pedido TO authenticated",
)

PRIVILEGIOS_DESCIDA = (
    "GRANT SELECT ON ALL TABLES IN SCHEMA public TO anon",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO authenticated",
    "ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT SELECT ON TABLES TO anon",
    "ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public "
    "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO authenticated",
)

FUNCOES = (
    """
    CREATE OR REPLACE FUNCTION public.app_usuario_id()
    RETURNS uuid
    LANGUAGE sql
    STABLE
    SECURITY DEFINER
    SET search_path = public, pg_temp
    AS $fn$
        SELECT u.id_usuario
        FROM public.usuario u
        WHERE u.auth_user_id = (SELECT auth.uid()) AND u.ativo
        LIMIT 1
    $fn$
    """,
    """
    CREATE OR REPLACE FUNCTION public.app_papel()
    RETURNS text
    LANGUAGE sql
    STABLE
    SET search_path = public, pg_temp
    AS $fn$
        SELECT (SELECT auth.jwt()) ->> 'papel'
    $fn$
    """,
    """
    CREATE OR REPLACE FUNCTION public.app_loja_id()
    RETURNS uuid
    LANGUAGE sql
    STABLE
    SET search_path = public, pg_temp
    AS $fn$
        SELECT NULLIF((SELECT auth.jwt()) ->> 'loja_id', '')::uuid
    $fn$
    """,
    """
    CREATE OR REPLACE FUNCTION public.app_papel_na_loja(p_loja uuid, p_papeis text[])
    RETURNS boolean
    LANGUAGE sql
    STABLE
    SET search_path = public, pg_temp
    AS $fn$
        SELECT COALESCE(
            public.app_usuario_id() IS NOT NULL
            AND (
                public.app_papel() = 'admin'
                OR (
                    public.app_papel() = ANY (p_papeis)
                    AND p_loja IS NOT NULL
                    AND p_loja = public.app_loja_id()
                )
            ),
            false
        )
    $fn$
    """,
    """
    CREATE OR REPLACE FUNCTION public.app_pode_ver_atendimento(p_atendimento uuid)
    RETURNS boolean
    LANGUAGE sql
    STABLE
    SECURITY DEFINER
    SET search_path = public, pg_temp
    AS $fn$
        SELECT EXISTS (
            SELECT 1
            FROM public.atendimento a
            WHERE a.id_atendimento = p_atendimento
              AND (
                  a.id_cliente = public.app_usuario_id()
                  OR public.app_papel_na_loja(a.id_loja, ARRAY['atendente', 'gerente_loja'])
              )
        )
    $fn$
    """,
    """
    CREATE OR REPLACE FUNCTION public.app_atendimento_aceita_mensagem(p_atendimento uuid)
    RETURNS boolean
    LANGUAGE sql
    STABLE
    SECURITY DEFINER
    SET search_path = public, pg_temp
    AS $fn$
        SELECT public.app_pode_ver_atendimento(p_atendimento)
            AND EXISTS (
                SELECT 1
                FROM public.atendimento a
                JOIN public.status_atendimento s
                    ON s.id_status_atendimento = a.id_status_atendimento
                WHERE a.id_atendimento = p_atendimento
                  AND s.codigo IN ('aberto', 'em_andamento', 'aguardando_cliente')
            )
    $fn$
    """,
    """
    CREATE OR REPLACE FUNCTION public.app_pode_avaliar_atendimento(p_atendimento uuid)
    RETURNS boolean
    LANGUAGE sql
    STABLE
    SECURITY DEFINER
    SET search_path = public, pg_temp
    AS $fn$
        SELECT EXISTS (
            SELECT 1
            FROM public.atendimento a
            JOIN public.status_atendimento s
                ON s.id_status_atendimento = a.id_status_atendimento
            WHERE a.id_atendimento = p_atendimento
              AND a.id_cliente = public.app_usuario_id()
              AND s.codigo IN ('resolvido', 'encerrado')
        )
    $fn$
    """,
)


def upgrade() -> None:
    op.execute(LIGAR_RLS_EM_TODAS_AS_TABELAS)
    for comando in PRIVILEGIOS_SUBIDA:
        op.execute(comando)
    for comando in FUNCOES:
        op.execute(comando)
    for assinatura in ASSINATURAS_FUNCOES:
        op.execute(f"REVOKE ALL ON FUNCTION public.{assinatura} FROM PUBLIC, anon")
        op.execute(f"GRANT EXECUTE ON FUNCTION public.{assinatura} TO authenticated")


def downgrade() -> None:
    for assinatura in reversed(ASSINATURAS_FUNCOES):
        op.execute(f"DROP FUNCTION IF EXISTS public.{assinatura}")
    for comando in PRIVILEGIOS_DESCIDA:
        op.execute(comando)
    op.execute(DESLIGAR_FORCE_EM_TODAS_AS_TABELAS)
