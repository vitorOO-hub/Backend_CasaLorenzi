"""clientes do Vulto+ no cadastro e extrato de pontos com validade

Revision ID: 20261021150000
Revises: 20261021140000
Create Date: 2026-10-21 15:00:00

- `usuario` nao ganha colunas: o cliente do Vulto+ usa nome, email, telefone, documento (CPF),
  id_loja (loja de cadastro) e criado_em.
- E-mail fica opcional para cliente (parte dos clientes do Vulto+ nao tem); continua unico quando
  existe e continua obrigatorio para a equipe (validado no trigger de `usuario`).
- Cliente sem login (importado do Vulto+, ainda sem conta no site) entra sem endereco: o endereco
  passa a ser exigido quando ele o editar, como ja acontece com os clientes antigos. Cliente que se
  cadastra pelo site (sempre com login) continua obrigado.
- Cadastro pelo site passa a exigir CPF (`documento` nos metadados). Se existe cliente importado
  sem login com o mesmo CPF e o mesmo e-mail, o cadastro assume essa linha (e os
  pontos dela). CPF de outra conta barra o cadastro. Importado sem e-mail e ligado pelo atendimento.
- `movimento_pontos`: extrato de pontos (credito, resgate, estorno, ajuste, vencimento). Cada
  credito guarda `vence_em` (365 dias); o saldo e a soma dos pontos.
- `resgate_pontos`: resgate com desconto, loja, atendente e observacao.
- RLS ligado, forcado e sem policy nas duas tabelas: so a conexao do FastAPI (que ignora RLS) le
  e escreve.
"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "20261021150000"
down_revision: str | Sequence[str] | None = "20261021140000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

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
        IF NEW.email IS NULL THEN
            RAISE EXCEPTION 'Conta da equipe precisa de e-mail' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF TG_OP = 'UPDATE' THEN
        v_mudou := (NEW.rua, NEW.bairro, NEW.numero_endereco, NEW.cep)
                   IS DISTINCT FROM (OLD.rua, OLD.bairro, OLD.numero_endereco, OLD.cep);
        v_completo_antes := OLD.rua IS NOT NULL AND OLD.bairro IS NOT NULL
                            AND OLD.numero_endereco IS NOT NULL AND OLD.cep IS NOT NULL;
    END IF;

    -- Cliente sem login (importado do Vulto+) pode entrar sem endereco nenhum; o endereco e
    -- exigido, completo, quando houver login ou quando alguem preencher parte dele.
    IF (TG_OP = 'INSERT' AND (NEW.auth_user_id IS NOT NULL OR NEW.rua IS NOT NULL
                              OR NEW.bairro IS NOT NULL OR NEW.numero_endereco IS NOT NULL
                              OR NEW.complemento IS NOT NULL OR NEW.cep IS NOT NULL))
       OR v_mudou OR v_completo_antes THEN
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
    v_cpf text := regexp_replace(COALESCE(m ->> 'documento', ''), '\\D', '', 'g');
    v_email text := lower(btrim(NEW.email));
    v_importado uuid;
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
    IF length(v_cpf) <> 11 THEN
        RAISE EXCEPTION 'CPF invalido' USING ERRCODE = '23514';
    END IF;

    -- Cliente importado do Vulto+ ainda sem login: o cadastro assume a linha (e os pontos)
    -- so quando CPF e e-mail batem, para ninguem tomar a conta de outra pessoa pelo CPF.
    SELECT u.id_usuario INTO v_importado FROM public.usuario u
    JOIN public.tipo_usuario t ON t.id_tipo_usuario = u.id_tipo_usuario
    WHERE u.documento = v_cpf AND t.codigo = 'cliente' AND u.auth_user_id IS NULL
      AND u.email = v_email
    FOR UPDATE OF u;
    IF FOUND THEN
        UPDATE public.usuario SET
            auth_user_id = NEW.id, nome = v_nome, telefone = v_telefone,
            rua = btrim(m ->> 'rua'), bairro = btrim(m ->> 'bairro'),
            numero_endereco = btrim(m ->> 'numero_endereco'),
            complemento = NULLIF(btrim(COALESCE(m ->> 'complemento', '')), ''), cep = v_cep,
            ativo = true, atualizado_em = now()
        WHERE id_usuario = v_importado;
        RETURN NEW;
    END IF;
    IF EXISTS (SELECT 1 FROM public.usuario WHERE documento = v_cpf) THEN
        RAISE EXCEPTION 'CPF ja cadastrado: fale com o atendimento' USING ERRCODE = '23505';
    END IF;

    -- O cargo e fixo: nada dos metadados (que o usuario edita) escolhe tipo, loja ou ativo.
    INSERT INTO public.usuario (
        id_tipo_usuario, auth_user_id, nome, email, telefone, documento,
        rua, bairro, numero_endereco, complemento, cep)
    VALUES (
        (SELECT id_tipo_usuario FROM public.tipo_usuario WHERE codigo = 'cliente'),
        NEW.id, v_nome, v_email, v_telefone, v_cpf,
        btrim(m ->> 'rua'), btrim(m ->> 'bairro'), btrim(m ->> 'numero_endereco'),
        NULLIF(btrim(COALESCE(m ->> 'complemento', '')), ''), v_cep);
    RETURN NEW;
END
$fn$
"""

REVOGAR_CADASTRO = (
    "REVOKE ALL ON FUNCTION public.criar_cliente_no_cadastro() FROM PUBLIC, anon, authenticated"
)

SUBIDA = (
    "ALTER TABLE public.usuario ALTER COLUMN email DROP NOT NULL",
    FUNCAO_VALIDAR,
    FUNCAO_CADASTRO,
    REVOGAR_CADASTRO,
    """
    CREATE TABLE public.movimento_pontos (
        id_movimento UUID NOT NULL DEFAULT gen_random_uuid(),
        id_usuario UUID NOT NULL,
        tipo TEXT NOT NULL,
        pontos INTEGER NOT NULL,
        ocorrido_em TIMESTAMPTZ NOT NULL,
        vence_em TIMESTAMPTZ,
        descricao TEXT NOT NULL,
        origem TEXT NOT NULL DEFAULT 'sistema',
        criado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT pk_movimento_pontos PRIMARY KEY (id_movimento),
        CONSTRAINT fk_movimento_pontos_usuario FOREIGN KEY (id_usuario)
            REFERENCES public.usuario (id_usuario) ON UPDATE CASCADE ON DELETE CASCADE,
        CONSTRAINT chk_movimento_pontos_tipo
            CHECK (tipo IN ('credito', 'resgate', 'estorno', 'ajuste', 'vencimento')),
        CONSTRAINT chk_movimento_pontos_sinal CHECK (
            pontos <> 0
            AND (tipo <> 'credito' OR pontos > 0)
            AND (tipo NOT IN ('resgate', 'vencimento') OR pontos < 0)
        ),
        CONSTRAINT chk_movimento_pontos_validade CHECK (vence_em IS NULL OR pontos > 0)
    )
    """,
    "CREATE INDEX idx_movimento_pontos_usuario "
    "ON public.movimento_pontos (id_usuario, ocorrido_em)",
    "ALTER TABLE public.movimento_pontos ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.movimento_pontos FORCE ROW LEVEL SECURITY",
    """
    CREATE TABLE public.resgate_pontos (
        id_resgate UUID NOT NULL DEFAULT gen_random_uuid(),
        id_usuario UUID NOT NULL,
        resgatado_em TIMESTAMPTZ NOT NULL,
        pontos INTEGER NOT NULL,
        desconto NUMERIC(12,2) NOT NULL,
        id_loja UUID,
        atendente TEXT,
        observacao TEXT,
        origem TEXT NOT NULL DEFAULT 'sistema',
        criado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT pk_resgate_pontos PRIMARY KEY (id_resgate),
        CONSTRAINT fk_resgate_pontos_usuario FOREIGN KEY (id_usuario)
            REFERENCES public.usuario (id_usuario) ON UPDATE CASCADE ON DELETE CASCADE,
        CONSTRAINT fk_resgate_pontos_loja FOREIGN KEY (id_loja)
            REFERENCES public.loja (id_loja) ON UPDATE CASCADE ON DELETE RESTRICT,
        CONSTRAINT chk_resgate_pontos_pontos CHECK (pontos > 0),
        CONSTRAINT chk_resgate_pontos_desconto CHECK (desconto >= 0)
    )
    """,
    "CREATE INDEX idx_resgate_pontos_usuario ON public.resgate_pontos (id_usuario, resgatado_em)",
    "ALTER TABLE public.resgate_pontos ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.resgate_pontos FORCE ROW LEVEL SECURITY",
)


def _anterior():
    """As versoes das funcoes que esta migration substitui (migration 20261007200000)."""
    caminho = Path(__file__).with_name("20261007200000_cliente_endereco_e_cadastro.py")
    spec = importlib.util.spec_from_file_location("_migracao_20261007200000", caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def upgrade() -> None:
    for comando in SUBIDA:
        op.execute(comando)


def downgrade() -> None:
    anterior = _anterior()
    # Falha de proposito se ja houver usuario sem e-mail: decidir o que fazer com eles antes.
    for comando in (
        "DROP TABLE IF EXISTS public.resgate_pontos",
        "DROP TABLE IF EXISTS public.movimento_pontos",
        anterior.FUNCAO_CADASTRO,
        REVOGAR_CADASTRO,
        anterior.FUNCAO_VALIDAR,
        "ALTER TABLE public.usuario ALTER COLUMN email SET NOT NULL",
    ):
        op.execute(comando)
