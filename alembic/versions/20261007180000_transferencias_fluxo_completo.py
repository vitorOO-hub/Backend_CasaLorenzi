"""transferencias: fluxo completo (recebida, recusada) e policies de leitura

Revision ID: 20261007180000
Revises: 20261007170000
Create Date: 2026-10-07 18:00:00

O fluxo da tela e: a loja de destino pede, a origem aceita (e a peca sai do estoque dela), o destino
confirma o recebimento (e a peca entra no dele) ou a origem recusa. Antes so existiam `solicitada` e
`aceita`. Aqui entram os status `recebida` e `recusada`, a data/pessoa do recebimento e o motivo da
recusa.

Seguranca: as escritas continuam so pela API (que confere papel e loja e trava as linhas do
estoque); o front nao tem INSERT/UPDATE/DELETE. Para leitura direta (e Realtime) ganham policy
de SELECT: transferencias para a equipe das duas lojas envolvidas, e ajustes de estoque para o
gerente da loja (o operador ve so os que ele mesmo pediu). Admin ve tudo (helper app_papel_na_loja).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261007180000"
down_revision: str | Sequence[str] | None = "20261007170000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EQUIPE = "ARRAY['operador_estoque', 'gerente_loja']"
POLITICAS = (
    (
        "tipo_transferencia_estoque - leitura por usuarios logados",
        "tipo_transferencia_estoque",
        "FOR SELECT TO authenticated USING (ativo)",
    ),
    (
        "status_transferencia_estoque - leitura por usuarios logados",
        "status_transferencia_estoque",
        "FOR SELECT TO authenticated USING (ativo)",
    ),
    (
        "transferencia_estoque - leitura pela equipe das lojas envolvidas",
        "transferencia_estoque",
        "FOR SELECT TO authenticated USING ("
        f"public.app_papel_na_loja(id_loja_origem, {EQUIPE}) "
        f"OR public.app_papel_na_loja(id_loja_destino, {EQUIPE}))",
    ),
    (
        "ajuste_estoque - leitura pela gestao da loja ou por quem pediu",
        "ajuste_estoque",
        "FOR SELECT TO authenticated USING ("
        "public.app_papel_na_loja(id_loja, ARRAY['gerente_loja']) "
        "OR (public.app_papel_na_loja(id_loja, ARRAY['operador_estoque']) "
        "AND id_usuario_solicitante = (SELECT public.app_usuario_id())))",
    ),
)
TABELAS_LIDAS = tuple(tabela for _n, tabela, _c in POLITICAS)

SUBIDA = (
    """
    INSERT INTO status_transferencia_estoque (codigo, nome, descricao, ordem)
    VALUES
        ('recebida', 'Recebida', 'Transferencia recebida e creditada na loja de destino.', 3),
        ('recusada', 'Recusada', 'Transferencia ou reposicao recusada pela loja de origem.', 4)
    ON CONFLICT (codigo) DO UPDATE
    SET nome = EXCLUDED.nome, descricao = EXCLUDED.descricao, ordem = EXCLUDED.ordem, ativo = TRUE
    """,
    "ALTER TABLE public.transferencia_estoque ADD COLUMN IF NOT EXISTS recebida_em TIMESTAMPTZ",
    "ALTER TABLE public.transferencia_estoque ADD COLUMN IF NOT EXISTS id_usuario_recebedor UUID",
    "ALTER TABLE public.transferencia_estoque ADD COLUMN IF NOT EXISTS motivo_recusa TEXT",
    # As transferencias de exemplo (scripts/semear_vendas.py) ja creditaram o destino quando foram
    # criadas como "aceita"; no fluxo novo isso e "recebida".
    """
    UPDATE public.transferencia_estoque t
    SET id_status_transferencia_estoque = (
            SELECT id_status_transferencia_estoque FROM public.status_transferencia_estoque
            WHERE codigo = 'recebida'),
        recebida_em = t.aceita_em + interval '1 second'
    WHERE t.observacao = 'Reposição combinada entre lojas'
      AND t.id_status_transferencia_estoque = (
            SELECT id_status_transferencia_estoque FROM public.status_transferencia_estoque
            WHERE codigo = 'aceita')
    """,
    "ALTER TABLE public.transferencia_estoque "
    "DROP CONSTRAINT IF EXISTS fk_transferencia_estoque_recebedor",
    """
    ALTER TABLE public.transferencia_estoque ADD CONSTRAINT fk_transferencia_estoque_recebedor
        FOREIGN KEY (id_usuario_recebedor) REFERENCES public.usuario (id_usuario)
        ON UPDATE CASCADE ON DELETE RESTRICT
    """,
    "ALTER TABLE public.transferencia_estoque "
    "DROP CONSTRAINT IF EXISTS chk_transferencia_estoque_motivo_recusa",
    "ALTER TABLE public.transferencia_estoque ADD CONSTRAINT "
    "chk_transferencia_estoque_motivo_recusa "
    "CHECK (motivo_recusa IS NULL OR length(trim(motivo_recusa)) > 0)",
    f"GRANT SELECT ON {', '.join('public.' + t for t in TABELAS_LIDAS)} TO authenticated",
    *(
        statement
        for nome, tabela, corpo in POLITICAS
        for statement in (
            f'DROP POLICY IF EXISTS "{nome}" ON public.{tabela}',
            f'CREATE POLICY "{nome}" ON public.{tabela} {corpo}',
        )
    ),
)

DESCIDA = (
    *(
        f'DROP POLICY IF EXISTS "{nome}" ON public.{tabela}'
        for nome, tabela, _c in reversed(POLITICAS)
    ),
    f"REVOKE SELECT ON {', '.join('public.' + t for t in TABELAS_LIDAS)} FROM authenticated",
    "ALTER TABLE public.transferencia_estoque "
    "DROP CONSTRAINT IF EXISTS chk_transferencia_estoque_motivo_recusa",
    "ALTER TABLE public.transferencia_estoque "
    "DROP CONSTRAINT IF EXISTS fk_transferencia_estoque_recebedor",
    "ALTER TABLE public.transferencia_estoque DROP COLUMN IF EXISTS motivo_recusa",
    "ALTER TABLE public.transferencia_estoque DROP COLUMN IF EXISTS id_usuario_recebedor",
    "ALTER TABLE public.transferencia_estoque DROP COLUMN IF EXISTS recebida_em",
    """
    DELETE FROM public.status_transferencia_estoque s
    WHERE s.codigo IN ('recebida', 'recusada')
      AND NOT EXISTS (
          SELECT 1 FROM public.transferencia_estoque t
          WHERE t.id_status_transferencia_estoque = s.id_status_transferencia_estoque
      )
    """,
)


def upgrade() -> None:
    for comando in SUBIDA:
        op.execute(comando)


def downgrade() -> None:
    for comando in DESCIDA:
        op.execute(comando)
