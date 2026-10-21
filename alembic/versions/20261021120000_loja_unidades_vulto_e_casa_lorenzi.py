"""loja: copia as unidades vulto* e a casa lorenzi padrao para a tabela loja

Revision ID: 20261021120000
Revises: 20261020130000
Create Date: 2026-10-21 12:00:00

- Cada unidade cujo nome comeca com "vulto" e a unidade "casa lorenzi" ganham uma linha em
  `loja`, com o MESMO uuid (`loja.id_loja` = `unidade.id_unidade`).
- `unidade` nao e alterada e `produto.id_unidade` continua apontando para ela; como os ids sao
  iguais, uma troca futura da FK para `loja` nao precisa converter nenhum valor.
- `codigo` = "LOJA-" + nome em maiusculas ("vulto batel" -> LOJA-VULTO-BATEL).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261021120000"
down_revision: str | Sequence[str] | None = "20261020130000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UNIDADES_PARA_LOJA = "u.nome = 'casa lorenzi' OR u.nome LIKE 'vulto%'"


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO public.loja (id_loja, codigo, nome, cidade)
        SELECT u.id_unidade,
               'LOJA-' || upper(regexp_replace(u.nome, '[^a-zA-Z0-9]+', '-', 'g')),
               u.nome,
               u.cidade
        FROM public.unidade u
        WHERE {UNIDADES_PARA_LOJA}
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DELETE FROM public.loja l
        USING public.unidade u
        WHERE l.id_loja = u.id_unidade AND ({UNIDADES_PARA_LOJA})
        """
    )
