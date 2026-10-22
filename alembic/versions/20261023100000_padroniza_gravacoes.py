"""normaliza dados cadastrais em toda gravacao

Revision ID: 20261023100000
Revises: 20261022210000
Create Date: 2026-10-23 10:00:00

As mesmas regras da migration 20261022210000 passam a valer em INSERT e UPDATE,
independentemente de a escrita vir da API, de um importador ou do SQL Editor.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261023100000"
down_revision: str | Sequence[str] | None = "20261022210000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABELAS = (
    "usuario",
    "loja",
    "unidade",
    "produto",
    "variacao_produto",
    "agendamento_cliente",
    "resgate_pontos",
)

FUNCAO = r"""
CREATE OR REPLACE FUNCTION public.normaliza_gravacao_cadastral()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp
AS $fn$
BEGIN
    IF TG_TABLE_NAME = 'usuario' THEN
        NEW.nome := COALESCE(public.texto_padrao(NEW.nome), NEW.nome);
        NEW.email := NULLIF(lower(btrim(NEW.email)), '');
        NEW.cidade := public.texto_padrao(NEW.cidade);
        NEW.rua := public.texto_padrao(NEW.rua);
        NEW.bairro := public.texto_padrao(NEW.bairro);
        NEW.numero_endereco := public.texto_padrao(NEW.numero_endereco);
        NEW.complemento := public.texto_padrao(NEW.complemento);
        NEW.telefone := public.telefone_padrao(NEW.telefone);
        NEW.documento := NULLIF(regexp_replace(NEW.documento, '\D', '', 'g'), '');
    ELSIF TG_TABLE_NAME = 'loja' THEN
        NEW.nome := COALESCE(public.texto_padrao(NEW.nome), NEW.nome);
        NEW.cidade := public.texto_padrao(NEW.cidade);
        NEW.endereco := public.texto_padrao(NEW.endereco);
        NEW.email := NULLIF(lower(btrim(NEW.email)), '');
        NEW.telefone := public.telefone_padrao(NEW.telefone);
    ELSIF TG_TABLE_NAME = 'unidade' THEN
        NEW.nome := COALESCE(public.texto_padrao(NEW.nome), NEW.nome);
        NEW.cidade := public.texto_padrao(NEW.cidade);
    ELSIF TG_TABLE_NAME = 'produto' THEN
        NEW.nome := COALESCE(public.texto_padrao(NEW.nome), NEW.nome);
        NEW.marca := COALESCE(public.texto_padrao(NEW.marca), NEW.marca);
        NEW.categoria := public.texto_padrao(NEW.categoria);
        NEW.colecao := regexp_replace(public.texto_padrao(NEW.colecao), '\mverao\M', 'verão', 'g');
        NEW.tipo := public.texto_padrao(NEW.tipo);
        NEW.tecido := public.texto_padrao(NEW.tecido);
        NEW.tecelagem := public.texto_padrao(NEW.tecelagem);
        NEW.costurado_em := public.texto_padrao(NEW.costurado_em);
        NEW.imagem_alt := public.texto_padrao(NEW.imagem_alt);
    ELSIF TG_TABLE_NAME = 'variacao_produto' THEN
        NEW.cor := public.texto_padrao(NEW.cor);
    ELSIF TG_TABLE_NAME = 'agendamento_cliente' THEN
        NEW.nome_contato := COALESCE(public.texto_padrao(NEW.nome_contato), NEW.nome_contato);
        NEW.peca_nome := public.texto_padrao(NEW.peca_nome);
        NEW.telefone_contato := public.telefone_padrao(NEW.telefone_contato);
    ELSIF TG_TABLE_NAME = 'resgate_pontos' THEN
        NEW.atendente := public.texto_padrao(NEW.atendente);
    ELSE
        RAISE EXCEPTION 'Tabela sem regra de padronizacao: %', TG_TABLE_NAME;
    END IF;
    RETURN NEW;
END
$fn$
"""


def upgrade() -> None:
    op.execute(FUNCAO)
    for tabela in TABELAS:
        op.execute(
            f"CREATE TRIGGER trg_{tabela}_normaliza_gravacao "
            f"BEFORE INSERT OR UPDATE ON public.{tabela} "
            "FOR EACH ROW EXECUTE FUNCTION public.normaliza_gravacao_cadastral()"
        )


def downgrade() -> None:
    for tabela in TABELAS:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{tabela}_normaliza_gravacao ON public.{tabela}")
    op.execute("DROP FUNCTION IF EXISTS public.normaliza_gravacao_cadastral()")
