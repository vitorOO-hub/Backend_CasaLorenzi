"""policies de atendimento, mensagem, avaliacao, usuario e opcoes

Revision ID: 20261007000300
Revises: 20261007000200
Create Date: 2026-10-07 00:03:00

Todas as policies sao TO authenticated. Nao ha policy de UPDATE nem DELETE: escrita so pela
API. O front insere direto apenas mensagem e avaliacao (CLAUDE.md, secao 6).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261007000300"
down_revision: str | Sequence[str] | None = "20261007000200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABELAS_DE_OPCOES = (
    "status_atendimento",
    "categoria_atendimento",
    "canal_atendimento",
    "prioridade_atendimento",
    "tipo_usuario",
)

GRANT_SELECT = (
    "GRANT SELECT ON public.usuario, public.atendimento, public.atendimento_item, "
    "public.mensagem, public.avaliacao_atendimento, public.status_atendimento, "
    "public.categoria_atendimento, public.canal_atendimento, "
    "public.prioridade_atendimento, public.tipo_usuario TO authenticated"
)
GRANT_INSERT = "GRANT INSERT ON public.mensagem, public.avaliacao_atendimento TO authenticated"
REVOKE_TUDO = (
    "REVOKE SELECT ON public.usuario, public.atendimento, public.atendimento_item, "
    "public.mensagem, public.avaliacao_atendimento, public.status_atendimento, "
    "public.categoria_atendimento, public.canal_atendimento, "
    "public.prioridade_atendimento, public.tipo_usuario FROM authenticated",
    "REVOKE INSERT ON public.mensagem, public.avaliacao_atendimento FROM authenticated",
)

# (nome, tabela, corpo da policy)
POLITICAS = (
    (
        "usuario - leitura da propria linha",
        "usuario",
        "FOR SELECT TO authenticated USING (auth_user_id = (SELECT auth.uid()))",
    ),
    (
        "atendimento - leitura por dono ou equipe da loja",
        "atendimento",
        "FOR SELECT TO authenticated USING ("
        "id_cliente = (SELECT public.app_usuario_id()) "
        "OR public.app_papel_na_loja(id_loja, ARRAY['atendente', 'gerente_loja']))",
    ),
    (
        "atendimento_item - leitura por quem ve o atendimento",
        "atendimento_item",
        "FOR SELECT TO authenticated USING (public.app_pode_ver_atendimento(id_atendimento))",
    ),
    (
        "mensagem - leitura por quem ve o atendimento",
        "mensagem",
        "FOR SELECT TO authenticated USING (public.app_pode_ver_atendimento(id_atendimento))",
    ),
    (
        "mensagem - envio do proprio autor em chamado em andamento",
        "mensagem",
        "FOR INSERT TO authenticated WITH CHECK ("
        "id_usuario_remetente = (SELECT public.app_usuario_id()) "
        "AND public.app_atendimento_aceita_mensagem(id_atendimento))",
    ),
    (
        "avaliacao_atendimento - leitura por quem ve o atendimento",
        "avaliacao_atendimento",
        "FOR SELECT TO authenticated USING (public.app_pode_ver_atendimento(id_atendimento))",
    ),
    (
        "avaliacao_atendimento - avaliacao do dono apos resolvido",
        "avaliacao_atendimento",
        "FOR INSERT TO authenticated WITH CHECK ("
        "public.app_pode_avaliar_atendimento(id_atendimento))",
    ),
) + tuple(
    (
        f"{tabela} - leitura por usuarios logados",
        tabela,
        "FOR SELECT TO authenticated USING (ativo)",
    )
    for tabela in TABELAS_DE_OPCOES
)


def upgrade() -> None:
    op.execute(GRANT_SELECT)
    op.execute(GRANT_INSERT)
    for nome, tabela, corpo in POLITICAS:
        op.execute(f'DROP POLICY IF EXISTS "{nome}" ON public.{tabela}')
        op.execute(f'CREATE POLICY "{nome}" ON public.{tabela} {corpo}')


def downgrade() -> None:
    for nome, tabela, _corpo in reversed(POLITICAS):
        op.execute(f'DROP POLICY IF EXISTS "{nome}" ON public.{tabela}')
    for comando in REVOKE_TUDO:
        op.execute(comando)
