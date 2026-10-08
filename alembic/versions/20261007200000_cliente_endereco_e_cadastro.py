"""cliente: endereco obrigatorio e cadastro pelo proprio site

Revision ID: 20261007200000
Revises: 20261007190000
Create Date: 2026-10-07 20:00:00

- `usuario` ganha rua, bairro, numero_endereco, complemento (opcional) e cep. Sao campos so de
  CLIENTE: um trigger exige rua, bairro, numero e CEP em todo cliente novo (e nao deixa um cliente
  completo ficar incompleto) e recusa endereco em conta da equipe. Clientes antigos, criados antes
  desta regra, continuam como estao ate alguem editar o endereco deles.
- Cadastro pelo site: o front chama `auth.signUp` com os dados nos metadados do usuario e um
  trigger em `auth.users` cria a linha de `usuario` (tipo cliente). Duas travas de seguranca:
  o cargo e SEMPRE `cliente` (nunca vem dos metadados, que o usuario controla), e so age quando
  o metadado `cadastro_cliente` e verdadeiro, entao contas da equipe criadas pelo painel nao
  viram cliente. E-mail que ja existe no cadastro (inclusive de funcionario ainda sem login)
  faz o cadastro falhar, o que impede alguem de tomar a linha de outra pessoa.
- Cada cliente tem a propria sessao (JWT) e so le a propria linha (policy existente em `usuario`).

Se o banco nao deixar criar trigger em `auth.users` (permissao), a migration avisa e segue; o SQL
fica em supabase/cadastro_cliente_trigger.sql para rodar no SQL Editor.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261007200000"
down_revision: str | Sequence[str] | None = "20261007190000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUNAS = ("rua", "bairro", "numero_endereco", "complemento", "cep")

FUNCAO_VALIDAR = """
CREATE OR REPLACE FUNCTION public.validar_endereco_usuario()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $fn$
DECLARE
    v_tipo text;
    v_completo_antes boolean := false;
    v_mudou boolean := false;
BEGIN
    SELECT codigo INTO v_tipo FROM public.tipo_usuario
    WHERE id_tipo_usuario = NEW.id_tipo_usuario;

    IF v_tipo IS DISTINCT FROM 'cliente' THEN
        IF NEW.rua IS NOT NULL OR NEW.bairro IS NOT NULL OR NEW.numero_endereco IS NOT NULL
           OR NEW.complemento IS NOT NULL OR NEW.cep IS NOT NULL THEN
            RAISE EXCEPTION 'Endereco so existe para cliente' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF TG_OP = 'UPDATE' THEN
        v_mudou := (NEW.rua, NEW.bairro, NEW.numero_endereco, NEW.cep)
                   IS DISTINCT FROM (OLD.rua, OLD.bairro, OLD.numero_endereco, OLD.cep);
        v_completo_antes := OLD.rua IS NOT NULL AND OLD.bairro IS NOT NULL
                            AND OLD.numero_endereco IS NOT NULL AND OLD.cep IS NOT NULL;
    END IF;

    IF TG_OP = 'INSERT' OR v_mudou OR v_completo_antes THEN
        IF length(btrim(coalesce(NEW.rua, ''))) = 0
           OR length(btrim(coalesce(NEW.bairro, ''))) = 0
           OR length(btrim(coalesce(NEW.numero_endereco, ''))) = 0
           OR coalesce(NEW.cep, '') = '' THEN
            RAISE EXCEPTION 'Cliente precisa de rua, bairro, numero e CEP' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END
$fn$
"""

FUNCAO_CADASTRO = """
CREATE OR REPLACE FUNCTION public.criar_cliente_no_cadastro()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $fn$
DECLARE
    m jsonb := COALESCE(NEW.raw_user_meta_data, '{}'::jsonb);
    v_nome text := btrim(COALESCE(m ->> 'nome', ''));
    v_telefone text := regexp_replace(COALESCE(m ->> 'telefone', ''), '\\D', '', 'g');
    v_cep text := regexp_replace(COALESCE(m ->> 'cep', ''), '\\D', '', 'g');
BEGIN
    -- Contas da equipe (criadas pelo painel) nao trazem a marca e nao viram cliente.
    IF COALESCE(m ->> 'cadastro_cliente', '') <> 'true' THEN
        RETURN NEW;
    END IF;
    IF length(v_nome) < 2 THEN
        RAISE EXCEPTION 'Informe o nome' USING ERRCODE = '23514';
    END IF;
    IF length(v_telefone) NOT BETWEEN 10 AND 13 THEN
        RAISE EXCEPTION 'Telefone invalido' USING ERRCODE = '23514';
    END IF;
    IF length(v_cep) <> 8 THEN
        RAISE EXCEPTION 'CEP invalido' USING ERRCODE = '23514';
    END IF;
    -- O cargo e fixo: nada dos metadados (que o usuario edita) escolhe tipo, loja ou ativo.
    INSERT INTO public.usuario (
        id_tipo_usuario, auth_user_id, nome, email, telefone,
        rua, bairro, numero_endereco, complemento, cep)
    VALUES (
        (SELECT id_tipo_usuario FROM public.tipo_usuario WHERE codigo = 'cliente'),
        NEW.id, v_nome, lower(btrim(NEW.email)), v_telefone,
        btrim(m ->> 'rua'), btrim(m ->> 'bairro'), btrim(m ->> 'numero_endereco'),
        NULLIF(btrim(COALESCE(m ->> 'complemento', '')), ''), v_cep);
    RETURN NEW;
END
$fn$
"""

SUBIDA = (
    "ALTER TABLE public.usuario ADD COLUMN IF NOT EXISTS rua TEXT",
    "ALTER TABLE public.usuario ADD COLUMN IF NOT EXISTS bairro TEXT",
    "ALTER TABLE public.usuario ADD COLUMN IF NOT EXISTS numero_endereco TEXT",
    "ALTER TABLE public.usuario ADD COLUMN IF NOT EXISTS complemento TEXT",
    "ALTER TABLE public.usuario ADD COLUMN IF NOT EXISTS cep TEXT",
    "ALTER TABLE public.usuario DROP CONSTRAINT IF EXISTS chk_usuario_endereco_formato",
    """
    ALTER TABLE public.usuario ADD CONSTRAINT chk_usuario_endereco_formato CHECK (
        (cep IS NULL OR cep ~ '^[0-9]{8}$')
        AND (rua IS NULL OR length(btrim(rua)) BETWEEN 1 AND 160)
        AND (bairro IS NULL OR length(btrim(bairro)) BETWEEN 1 AND 120)
        AND (numero_endereco IS NULL OR length(btrim(numero_endereco)) BETWEEN 1 AND 20)
        AND (complemento IS NULL OR length(btrim(complemento)) BETWEEN 1 AND 120)
    )
    """,
    FUNCAO_VALIDAR,
    "DROP TRIGGER IF EXISTS trg_usuario_validar_endereco ON public.usuario",
    """
    CREATE TRIGGER trg_usuario_validar_endereco
    BEFORE INSERT OR UPDATE ON public.usuario
    FOR EACH ROW EXECUTE FUNCTION public.validar_endereco_usuario()
    """,
    FUNCAO_CADASTRO,
    "REVOKE ALL ON FUNCTION public.criar_cliente_no_cadastro() FROM PUBLIC, anon, authenticated",
    """
    DO $bloco$
    BEGIN
        IF to_regclass('auth.users') IS NOT NULL THEN
            BEGIN
                DROP TRIGGER IF EXISTS trg_criar_cliente_no_cadastro ON auth.users;
                CREATE TRIGGER trg_criar_cliente_no_cadastro
                AFTER INSERT ON auth.users
                FOR EACH ROW EXECUTE FUNCTION public.criar_cliente_no_cadastro();
            EXCEPTION WHEN insufficient_privilege THEN
                RAISE WARNING 'sem permissao em auth.users: crie o trigger do cadastro de cliente '
                    'pelo painel com supabase/cadastro_cliente_trigger.sql';
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
                DROP TRIGGER IF EXISTS trg_criar_cliente_no_cadastro ON auth.users;
            EXCEPTION WHEN insufficient_privilege THEN
                RAISE WARNING 'sem permissao em auth.users: remova o trigger pelo painel';
            END;
        END IF;
    END
    $bloco$
    """,
    "DROP FUNCTION IF EXISTS public.criar_cliente_no_cadastro()",
    "DROP TRIGGER IF EXISTS trg_usuario_validar_endereco ON public.usuario",
    "DROP FUNCTION IF EXISTS public.validar_endereco_usuario()",
    "ALTER TABLE public.usuario DROP CONSTRAINT IF EXISTS chk_usuario_endereco_formato",
    *(f"ALTER TABLE public.usuario DROP COLUMN IF EXISTS {coluna}" for coluna in COLUNAS),
)


def upgrade() -> None:
    for comando in SUBIDA:
        op.execute(comando)


def downgrade() -> None:
    for comando in DESCIDA:
        op.execute(comando)
