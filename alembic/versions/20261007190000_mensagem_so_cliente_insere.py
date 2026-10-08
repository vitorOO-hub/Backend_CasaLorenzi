"""mensagem: o front so insere direto como cliente; a equipe responde pela API

Revision ID: 20261007190000
Revises: 20261007180000
Create Date: 2026-10-07 19:00:00

A policy antiga deixava QUALQUER pessoa que enxerga o chamado inserir mensagem direto pela API
do Supabase, inclusive a equipe. Isso pulava as regras da API (chamado assumido por outra
pessoa, primeira resposta, assumir ao responder) e deixava um token de atendente escrever como
quiser. Agora o INSERT direto vale so para o cliente (token sem cargo) dono do chamado;
atendente, gerente e admin respondem pela API, que confere tudo e usa a identidade do token.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261007190000"
down_revision: str | Sequence[str] | None = "20261007180000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOME = "mensagem - envio do proprio autor em chamado em andamento"
ANTES = (
    "id_usuario_remetente = (SELECT public.app_usuario_id()) "
    "AND public.app_atendimento_aceita_mensagem(id_atendimento)"
)
DEPOIS = (
    "id_usuario_remetente = (SELECT public.app_usuario_id()) "
    "AND (SELECT public.app_papel()) IS NULL "
    "AND public.app_atendimento_aceita_mensagem(id_atendimento)"
)


def _recriar(condicao: str) -> None:
    op.execute(f'DROP POLICY IF EXISTS "{NOME}" ON public.mensagem')
    op.execute(
        f'CREATE POLICY "{NOME}" ON public.mensagem FOR INSERT TO authenticated '
        f"WITH CHECK ({condicao})"
    )


def upgrade() -> None:
    _recriar(DEPOIS)


def downgrade() -> None:
    _recriar(ANTES)
