"""chamados da fila geral: loja so por escolha e visiveis para a equipe

Revision ID: 20261014120000
Revises: 20261008110000
Create Date: 2026-10-14 12:00:00

- O trigger `trg_atendimento_preencher_id_loja` copiava a loja do pedido para o chamado. Com isso,
  um chamado aberto na "fila geral" com pedido vinculado caia na fila so da loja do pedido. Agora a
  loja do chamado e so a que o cliente escolheu (o pedido continua como contexto).
- As policies exigiam id_loja = loja do token, entao os chamados sem loja (fila geral) nunca
  chegavam a equipe pelo Realtime (Postgres Changes e canal privado "chamado:<uuid>"). Atendente e
  gerente de qualquer loja passam a enxerga-los, como a API ja fazia (Escopo.incluir_sem_loja).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261014120000"
down_revision: str | Sequence[str] | None = "20261008110000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLITICA = "atendimento - leitura por dono ou equipe da loja"

# Fila geral: chamado sem loja, visivel para atendente e gerente com cadastro ativo.
FILA_GERAL_NA_FUNCAO = """
              OR (
                  a.id_loja IS NULL
                  AND public.app_usuario_id() IS NOT NULL
                  AND public.app_papel() = ANY (ARRAY['atendente', 'gerente_loja'])
              )"""
FILA_GERAL_NA_POLITICA = """
    OR (
        id_loja IS NULL
        AND (SELECT public.app_usuario_id()) IS NOT NULL
        AND (SELECT public.app_papel()) = ANY (ARRAY['atendente', 'gerente_loja'])
    )"""


def _funcao_pode_ver(fila_geral: str) -> str:
    return f"""
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
                  OR public.app_papel_na_loja(
                      a.id_loja, ARRAY['atendente', 'gerente_loja']
                  ){fila_geral}
              )
        )
    $fn$
    """


def _politica(fila_geral: str) -> tuple[str, str]:
    return (
        f'DROP POLICY IF EXISTS "{POLITICA}" ON public.atendimento',
        f"""
        CREATE POLICY "{POLITICA}" ON public.atendimento
        FOR SELECT
        USING (
            id_cliente = (SELECT public.app_usuario_id())
            OR public.app_papel_na_loja(id_loja, ARRAY['atendente', 'gerente_loja']){fila_geral}
        )
        """,
    )


FUNCAO_PREENCHER_LOJA = """
CREATE OR REPLACE FUNCTION public.preencher_id_loja_atendimento()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $fn$
BEGIN
    IF NEW.id_loja IS NULL AND NEW.id_pedido IS NOT NULL THEN
        SELECT p.id_loja INTO NEW.id_loja
        FROM public.pedido p
        WHERE p.id_pedido = NEW.id_pedido;
    END IF;
    RETURN NEW;
END
$fn$
"""

SUBIDA = (
    "DROP TRIGGER IF EXISTS trg_atendimento_preencher_id_loja ON public.atendimento",
    "DROP FUNCTION IF EXISTS public.preencher_id_loja_atendimento()",
    _funcao_pode_ver(FILA_GERAL_NA_FUNCAO),
    *_politica(FILA_GERAL_NA_POLITICA),
)

DESCIDA = (
    *_politica(""),
    _funcao_pode_ver(""),
    FUNCAO_PREENCHER_LOJA,
    "DROP TRIGGER IF EXISTS trg_atendimento_preencher_id_loja ON public.atendimento",
    """
    CREATE TRIGGER trg_atendimento_preencher_id_loja
    BEFORE INSERT ON public.atendimento
    FOR EACH ROW EXECUTE FUNCTION public.preencher_id_loja_atendimento()
    """,
)


def upgrade() -> None:
    for comando in SUBIDA:
        op.execute(comando)


def downgrade() -> None:
    for comando in DESCIDA:
        op.execute(comando)
