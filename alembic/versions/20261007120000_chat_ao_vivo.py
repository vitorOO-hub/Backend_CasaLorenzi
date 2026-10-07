"""chat ao vivo: leitura por atendente, Realtime do Supabase e canais privados

Revision ID: 20261007120000
Revises: 20261007110000
Create Date: 2026-10-07 12:00:00

O chat usa a infraestrutura do Supabase Realtime, sem servidor de websocket proprio:

- Postgres Changes em `mensagem` e `atendimento`: o Realtime so entrega a cada pessoa as linhas que
  as policies de RLS (migrations anteriores) deixam essa pessoa ler. Para isso as duas tabelas
  entram na publicacao `supabase_realtime`.
- Broadcast e Presence (digitando, quem esta online) em canais PRIVADOS `chamado:<uuid>`: as
  policies de `realtime.messages` abaixo so liberam o canal a quem enxerga aquele atendimento.
- `chamado_leitura`: ate quando cada pessoa leu cada conversa (base do contador de nao lidas). Fica
  fechada ao front: so a API le e grava.

A policy em `realtime.messages` depende de o schema `realtime` existir e de permissao sobre ele. Se
faltar permissao, a migration segue com um aviso e as policies podem ser criadas pelo painel com o
SQL de `supabase/realtime_chat_policies.sql`.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261007120000"
down_revision: str | Sequence[str] | None = "20261007110000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLITICA_LER = "chat - receber presenca e digitacao do chamado"
POLITICA_ENVIAR = "chat - enviar presenca e digitacao do chamado"

UUID_RE = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

# O topico do canal e "chamado:<uuid>". O CASE garante que o cast so roda se o formato estiver certo
# (o SQL nao garante a ordem de avaliacao de um AND).
ACESSO_AO_CANAL = f"""
    extension IN ('broadcast', 'presence')
    AND CASE
        WHEN realtime.topic() ~ '^chamado:{UUID_RE}$'
        THEN public.app_pode_ver_atendimento(split_part(realtime.topic(), ':', 2)::uuid)
        ELSE false
    END
"""


def _se_realtime_existe(comandos: str) -> str:
    """Roda os comandos so se `realtime.messages` existir; sem permissao, avisa e segue."""
    return f"""
    DO $bloco$
    BEGIN
        IF to_regclass('realtime.messages') IS NOT NULL THEN
            BEGIN
                {comandos}
            EXCEPTION WHEN insufficient_privilege THEN
                RAISE WARNING 'sem permissao em realtime.messages: crie as policies do chat pelo '
                    'painel com supabase/realtime_chat_policies.sql';
            END;
        END IF;
    END
    $bloco$
    """


def _publicar(tabela: str) -> str:
    return f"""
    DO $bloco$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_publication WHERE pubname = 'supabase_realtime')
           AND NOT EXISTS (
               SELECT 1 FROM pg_publication_tables
               WHERE pubname = 'supabase_realtime' AND schemaname = 'public'
                 AND tablename = '{tabela}'
           ) THEN
            ALTER PUBLICATION supabase_realtime ADD TABLE public.{tabela};
        END IF;
    END
    $bloco$
    """


SUBIDA = (
    # ---- leitura por atendente ----
    """
    CREATE TABLE IF NOT EXISTS public.chamado_leitura (
        id_usuario UUID NOT NULL,
        id_atendimento UUID NOT NULL,
        lida_ate TIMESTAMPTZ NOT NULL DEFAULT now(),
        atualizada_em TIMESTAMPTZ NOT NULL DEFAULT now(),

        CONSTRAINT pk_chamado_leitura PRIMARY KEY (id_usuario, id_atendimento),
        CONSTRAINT fk_chamado_leitura_usuario FOREIGN KEY (id_usuario)
            REFERENCES public.usuario (id_usuario) ON UPDATE CASCADE ON DELETE CASCADE,
        CONSTRAINT fk_chamado_leitura_atendimento FOREIGN KEY (id_atendimento)
            REFERENCES public.atendimento (id_atendimento) ON UPDATE CASCADE ON DELETE CASCADE
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_chamado_leitura_atendimento "
    "ON public.chamado_leitura (id_atendimento)",
    "ALTER TABLE public.chamado_leitura ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.chamado_leitura FORCE ROW LEVEL SECURITY",
    "REVOKE ALL ON public.chamado_leitura FROM anon, authenticated",
    # ---- Realtime: Postgres Changes ----
    _publicar("mensagem"),
    _publicar("atendimento"),
    # ---- Realtime: canais privados (Broadcast e Presence) ----
    _se_realtime_existe(
        f'DROP POLICY IF EXISTS "{POLITICA_LER}" ON realtime.messages;\n'
        f'                DROP POLICY IF EXISTS "{POLITICA_ENVIAR}" ON realtime.messages;\n'
        f'                CREATE POLICY "{POLITICA_LER}" ON realtime.messages\n'
        f"                    FOR SELECT TO authenticated USING ({ACESSO_AO_CANAL});\n"
        f'                CREATE POLICY "{POLITICA_ENVIAR}" ON realtime.messages\n'
        f"                    FOR INSERT TO authenticated WITH CHECK ({ACESSO_AO_CANAL});"
    ),
)

DESCIDA = (
    _se_realtime_existe(
        f'DROP POLICY IF EXISTS "{POLITICA_ENVIAR}" ON realtime.messages;\n'
        f'                DROP POLICY IF EXISTS "{POLITICA_LER}" ON realtime.messages;'
    ),
    # A publicacao nao e desfeita: a tabela pode ter sido ligada ao Realtime pelo painel tambem.
    "DROP TABLE IF EXISTS public.chamado_leitura",
)


def upgrade() -> None:
    for comando in SUBIDA:
        op.execute(comando)


def downgrade() -> None:
    for comando in DESCIDA:
        op.execute(comando)
