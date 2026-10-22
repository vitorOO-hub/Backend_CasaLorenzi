"""atendimento.historico_vulto: atendimentos importados da Vulto ficam fora das filas

Revision ID: 20261023110000
Revises: 20261023100000
Create Date: 2026-10-23 11:00:00

- `atendimento.historico_vulto` (padrao falso) marca o atendimento que veio do historico da Vulto
  (scripts/importar_atendimentos_historicos.py). Nada do atendimento muda: situacao, mensagens,
  datas, cliente, canal e assunto ficam como foram importados.
- Ficam marcados os atendimentos da importacao: sem loja, abertos antes de o sistema entrar no ar
  (01/10/2026) e vindos de WhatsApp ou e-mail.
- Filas, contadores, chat ao vivo e paineis ignoram os marcados; a ficha do cliente e o "Meus
  chamados" do cliente mostram todos, com a marca.
- Mensagem nova num atendimento marcado tira a marca (trigger em `mensagem`), e ele volta para a
  fila: quem retoma um assunto antigo nao fica sem resposta. O trigger roda como dono da tabela
  porque o cliente tambem grava mensagem direto pelo Supabase (RLS).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261023110000"
down_revision: str | Sequence[str] | None = "20261023100000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INICIO_DO_SISTEMA = "2026-10-01 00:00:00-03"

SUBIDA = (
    "ALTER TABLE public.atendimento "
    "ADD COLUMN IF NOT EXISTS historico_vulto BOOLEAN NOT NULL DEFAULT false",
    f"""
    UPDATE public.atendimento a
    SET historico_vulto = true
    FROM public.canal_atendimento c
    WHERE c.id_canal_atendimento = a.id_canal_atendimento
      AND c.codigo IN ('whatsapp', 'email')
      AND a.id_loja IS NULL
      AND a.aberto_em < TIMESTAMPTZ '{INICIO_DO_SISTEMA}'
    """,
    """
    CREATE OR REPLACE FUNCTION public.atendimento_sai_do_historico()
    RETURNS trigger
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = public, pg_temp
    AS $fn$
    BEGIN
        UPDATE public.atendimento
        SET historico_vulto = false, atualizado_em = now()
        WHERE id_atendimento = NEW.id_atendimento AND historico_vulto;
        RETURN NEW;
    END
    $fn$
    """,
    "REVOKE ALL ON FUNCTION public.atendimento_sai_do_historico() FROM PUBLIC, anon, authenticated",
    "DROP TRIGGER IF EXISTS trg_mensagem_tira_historico_vulto ON public.mensagem",
    """
    CREATE TRIGGER trg_mensagem_tira_historico_vulto
    AFTER INSERT ON public.mensagem
    FOR EACH ROW EXECUTE FUNCTION public.atendimento_sai_do_historico()
    """,
)

DESCIDA = (
    "DROP TRIGGER IF EXISTS trg_mensagem_tira_historico_vulto ON public.mensagem",
    "DROP FUNCTION IF EXISTS public.atendimento_sai_do_historico()",
    "ALTER TABLE public.atendimento DROP COLUMN IF EXISTS historico_vulto",
)


def upgrade() -> None:
    for comando in SUBIDA:
        op.execute(comando)


def downgrade() -> None:
    for comando in DESCIDA:
        op.execute(comando)
