"""correcoes da auditoria: frete dos pedidos e conta excluida no Auth

Revision ID: 20261008110000
Revises: 20261008100000
Create Date: 2026-10-08 11:00:00

- Pedidos do checkout antigo gravaram o frete so no texto da observacao e deixaram `valor_frete` em
  0, entao `valor_total` nao fechava com itens + frete. O codigo novo grava a coluna; aqui acerta os
  pedidos que ficaram para tras (so quando o frete esta em 0 e o total passa dos itens).
- Excluir uma conta em `auth.users` deixava a linha de `usuario` ativa e ligada a um login que nao
  existe mais. O trigger novo desativa a linha e solta o vinculo (o e-mail continua reservado).

Se o banco nao deixar criar trigger em `auth.users` (permissao), a migration avisa e segue; o SQL
fica em supabase/excluir_conta_trigger.sql para rodar no SQL Editor.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261008110000"
down_revision: str | Sequence[str] | None = "20261008100000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCAO = """
CREATE OR REPLACE FUNCTION public.desativar_usuario_ao_excluir_conta()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $fn$
BEGIN
    UPDATE public.usuario
    SET ativo = false, auth_user_id = NULL, atualizado_em = now()
    WHERE auth_user_id = OLD.id;
    RETURN OLD;
END
$fn$
"""

SUBIDA = (
    """
    UPDATE public.pedido p
    SET valor_frete = p.valor_total - i.soma
    FROM (SELECT id_pedido, sum(valor_total) AS soma FROM public.item_pedido GROUP BY id_pedido) i
    WHERE i.id_pedido = p.id_pedido AND p.valor_frete = 0 AND p.valor_total > i.soma
    """,
    FUNCAO,
    "REVOKE ALL ON FUNCTION public.desativar_usuario_ao_excluir_conta() "
    "FROM PUBLIC, anon, authenticated",
    """
    DO $bloco$
    BEGIN
        IF to_regclass('auth.users') IS NOT NULL THEN
            BEGIN
                DROP TRIGGER IF EXISTS trg_desativar_usuario_ao_excluir_conta ON auth.users;
                CREATE TRIGGER trg_desativar_usuario_ao_excluir_conta
                AFTER DELETE ON auth.users
                FOR EACH ROW EXECUTE FUNCTION public.desativar_usuario_ao_excluir_conta();
            EXCEPTION WHEN insufficient_privilege THEN
                RAISE WARNING 'sem permissao em auth.users: crie o trigger de exclusao de conta '
                    'pelo painel com supabase/excluir_conta_trigger.sql';
            END;
        END IF;
    END
    $bloco$
    """,
)

DESCIDA = (
    """
    DO $bloco$
    BEGIN
        IF to_regclass('auth.users') IS NOT NULL THEN
            BEGIN
                DROP TRIGGER IF EXISTS trg_desativar_usuario_ao_excluir_conta ON auth.users;
            EXCEPTION WHEN insufficient_privilege THEN
                RAISE WARNING 'sem permissao em auth.users: remova o trigger pelo painel';
            END;
        END IF;
    END
    $bloco$
    """,
    "DROP FUNCTION IF EXISTS public.desativar_usuario_ao_excluir_conta()",
)


def upgrade() -> None:
    for comando in SUBIDA:
        op.execute(comando)


def downgrade() -> None:
    for comando in DESCIDA:
        op.execute(comando)
