"""dados no padrao do negocio: textos cadastrais em minusculas, telefone e CPF so com digitos

Revision ID: 20261022180000
Revises: 20261022170000
Create Date: 2026-10-22 18:00:00

- `texto_padrao(text)`: minusculas, sem espaco nas pontas e um espaco so entre as palavras
  ("  Fernanda   K. " -> "fernanda k."). `telefone_padrao(text)`: so digitos, DDD + numero, sem o
  55 nem o zero de operadora. As mesmas regras estao em `app/core/padroes.py`.
- O cadastro pelo site (`criar_cliente_no_cadastro`) passa a gravar nome e endereco no padrao e o
  telefone sem o 55. O resto da funcao e o da migration 20261021150000, sem mudanca.
- Padroniza o que ja esta gravado: usuario (nome, e-mail, cidade, endereco, telefone, CPF), loja
  (nome, cidade, endereco, e-mail, telefone), unidade, produto (nome, marca, categoria, colecao,
  tipo, tecido, tecelagem, costurado_em, imagem_alt), cor da variacao, contato do agendamento e
  atendente do resgate. A colecao "verao" vira "verão" (havia as duas grafias).
- Ficam como estao: codigos (SKU, EAN, tamanho, UF, numero do pedido, protocolo, codigo), URLs,
  textos escritos pelas pessoas (mensagens, observacoes, motivos), rotulos das tabelas de apoio,
  auditoria e a area de importacao (dado bruto, como chegou).
- Preco ja e numeric(12,2), data e hora ja e timestamptz e quantidade ja e inteiro: nada muda.
- O downgrade volta a funcao de cadastro anterior e apaga as duas funcoes. Os dados continuam no
  padrao: a grafia antiga nao tem como voltar.
"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "20261022180000"
down_revision: str | Sequence[str] | None = "20261022170000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCOES = (
    r"""
    CREATE OR REPLACE FUNCTION public.texto_padrao(p text)
    RETURNS text
    LANGUAGE sql
    IMMUTABLE
    PARALLEL SAFE
    SET search_path = pg_catalog, pg_temp
    AS $fn$
        SELECT NULLIF(lower(btrim(regexp_replace(p, '\s+', ' ', 'g'))), '')
    $fn$
    """,
    r"""
    CREATE OR REPLACE FUNCTION public.telefone_padrao(p text)
    RETURNS text
    LANGUAGE plpgsql
    IMMUTABLE
    PARALLEL SAFE
    SET search_path = pg_catalog, pg_temp
    AS $fn$
    DECLARE
        d text := regexp_replace(COALESCE(p, ''), '\D', '', 'g');
    BEGIN
        IF d = '' THEN
            RETURN NULL;
        END IF;
        IF length(d) IN (12, 13) AND left(d, 2) = '55' THEN
            d := substr(d, 3);
        END IF;
        IF length(d) IN (11, 12) AND left(d, 1) = '0' THEN
            d := substr(d, 2);
        END IF;
        RETURN d;
    END
    $fn$
    """,
)

# Cada padrao do banco aplicado a uma coluna (texto que nao pode ficar vazio guarda o original).
T = "public.texto_padrao({c})"
OBRIGATORIO = "COALESCE(public.texto_padrao({c}), {c})"
EMAIL = "NULLIF(lower(btrim({c})), '')"
FONE = "public.telefone_padrao({c})"
DIGITOS = r"NULLIF(regexp_replace({c}, '\D', '', 'g'), '')"
COLECAO = r"regexp_replace(public.texto_padrao({c}), '\mverao\M', 'verão', 'g')"

COLUNAS = {
    "usuario": {
        "nome": OBRIGATORIO,
        "email": EMAIL,
        "cidade": T,
        "rua": T,
        "bairro": T,
        "numero_endereco": T,
        "complemento": T,
        "telefone": FONE,
        "documento": DIGITOS,
    },
    "loja": {"nome": OBRIGATORIO, "cidade": T, "endereco": T, "email": EMAIL, "telefone": FONE},
    "unidade": {"nome": OBRIGATORIO, "cidade": T},
    "produto": {
        "nome": OBRIGATORIO,
        "marca": OBRIGATORIO,
        "categoria": T,
        "colecao": COLECAO,
        "tipo": T,
        "tecido": T,
        "tecelagem": T,
        "costurado_em": T,
        "imagem_alt": T,
    },
    "variacao_produto": {"cor": T},
    "agendamento_cliente": {"nome_contato": OBRIGATORIO, "peca_nome": T, "telefone_contato": FONE},
    "resgate_pontos": {"atendente": T},
}


def _ajuste(tabela: str, colunas: dict[str, str]) -> str:
    novos = {coluna: regra.format(c=coluna) for coluna, regra in colunas.items()}
    atribuicoes = ", ".join(f"{coluna} = {valor}" for coluna, valor in novos.items())
    antes = ", ".join(novos)
    depois = ", ".join(novos.values())
    # So reescreve a linha que muda (nao dispara trigger nem gera escrita a toa).
    return (
        f"UPDATE public.{tabela} SET {atribuicoes} "  # nosec B608 - nomes fixos deste arquivo
        f"WHERE ROW({antes}) IS DISTINCT FROM ROW({depois})"
    )


AJUSTES = tuple(_ajuste(tabela, colunas) for tabela, colunas in COLUNAS.items())


def _migracao_do_cadastro():
    """A funcao de cadastro em vigor (migration 20261021150000), lida do proprio arquivo."""
    caminho = Path(__file__).with_name("20261021150000_clientes_vulto_fidelidade.py")
    spec = importlib.util.spec_from_file_location("_migracao_20261021150000", caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


# (trecho atual, trecho novo, quantas vezes aparece): se a funcao anterior mudar, a migration para
# com erro em vez de gravar uma funcao pela metade.
TROCAS_NO_CADASTRO = (
    (
        "v_nome text := btrim(COALESCE(m ->> 'nome', ''));",
        "v_nome text := COALESCE(public.texto_padrao(m ->> 'nome'), '');",
        1,
    ),
    ("btrim(m ->> 'rua')", "public.texto_padrao(m ->> 'rua')", 2),
    ("btrim(m ->> 'bairro')", "public.texto_padrao(m ->> 'bairro')", 2),
    ("btrim(m ->> 'numero_endereco')", "public.texto_padrao(m ->> 'numero_endereco')", 2),
    (
        "NULLIF(btrim(COALESCE(m ->> 'complemento', '')), '')",
        "public.texto_padrao(m ->> 'complemento')",
        2,
    ),
    (
        "    -- Cliente importado do Vulto+ ainda sem login",
        "    v_telefone := public.telefone_padrao(v_telefone);\n\n"
        "    -- Cliente importado do Vulto+ ainda sem login",
        1,
    ),
)


def cadastro_no_padrao(funcao: str) -> str:
    for atual, novo, vezes in TROCAS_NO_CADASTRO:
        achadas = funcao.count(atual)
        if achadas != vezes:
            raise RuntimeError(
                f"criar_cliente_no_cadastro mudou: {atual!r} aparece {achadas} vez(es), "
                f"esperado {vezes}"
            )
        funcao = funcao.replace(atual, novo)
    return funcao


def upgrade() -> None:
    anterior = _migracao_do_cadastro()
    for comando in FUNCOES:
        op.execute(comando)
    op.execute(cadastro_no_padrao(anterior.FUNCAO_CADASTRO))
    op.execute(anterior.REVOGAR_CADASTRO)
    for comando in AJUSTES:
        op.execute(comando)


def downgrade() -> None:
    anterior = _migracao_do_cadastro()
    op.execute(anterior.FUNCAO_CADASTRO)
    op.execute(anterior.REVOGAR_CADASTRO)
    op.execute("DROP FUNCTION IF EXISTS public.telefone_padrao(text)")
    op.execute("DROP FUNCTION IF EXISTS public.texto_padrao(text)")
