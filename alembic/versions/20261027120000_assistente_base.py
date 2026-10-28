"""assistente e automacoes: consentimento, avisos de pontos, embeddings, horario e conversas

Revision ID: 20261027120000
Revises: 20261027100000
Create Date: 2026-10-27 12:00:00

Base de dados dos assistentes (cliente e diretoria) e das automacoes do n8n (Entrega 4, ver
docs/superpowers/specs/2026-10-27-assistente-base-design.md):

- `usuario.aceita_mensagens`: quem pode receber aviso por e-mail ou WhatsApp. Sem informacao, `true`
  (decisao do time); so fica `false` quem disse nao (planilha da Vulto ou o proprio cliente).
- `aviso_pontos`: o aviso de cada lote de pontos sai uma vez por canal.
- `produto.embedding` (pgvector, 768 dimensoes, cosseno): busca da peca pela descricao.
- `loja.horario_funcionamento`: objeto `seg`..`dom` com `{abre, fecha}` (ou `null` = fechada).
- `conversa_assistente` e `mensagem_assistente`: memoria da conversa, passagem para o atendente,
  perguntas sem resposta e tokens gastos.

As tabelas novas tem RLS ligado e forcado sem policies: so o FastAPI (que ignora RLS) le e grava.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261027120000"
down_revision: str | Sequence[str] | None = "20261027100000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DIMENSOES_EMBEDDING = 768

SUBIDA = (
    # ---- consentimento de mensagens ----
    "ALTER TABLE public.usuario ADD COLUMN IF NOT EXISTS aceita_mensagens BOOLEAN NOT NULL "
    "DEFAULT true",
    "ALTER TABLE public.usuario ADD COLUMN IF NOT EXISTS aceita_mensagens_origem TEXT NOT NULL "
    "DEFAULT 'padrao'",
    "ALTER TABLE public.usuario ADD COLUMN IF NOT EXISTS aceita_mensagens_em TIMESTAMPTZ",
    "ALTER TABLE public.usuario DROP CONSTRAINT IF EXISTS chk_usuario_aceita_mensagens_origem",
    "ALTER TABLE public.usuario ADD CONSTRAINT chk_usuario_aceita_mensagens_origem "
    "CHECK (aceita_mensagens_origem IN ('padrao', 'planilha_vulto', 'cliente'))",
    # ---- avisos de pontos ja enviados ----
    """
    CREATE TABLE IF NOT EXISTS public.aviso_pontos (
        id_aviso UUID NOT NULL DEFAULT gen_random_uuid(),
        id_usuario UUID NOT NULL,
        vence_em TIMESTAMPTZ NOT NULL,
        pontos INTEGER NOT NULL,
        canal TEXT NOT NULL,
        enviado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT pk_aviso_pontos PRIMARY KEY (id_aviso),
        CONSTRAINT fk_aviso_pontos_usuario FOREIGN KEY (id_usuario)
            REFERENCES public.usuario (id_usuario) ON UPDATE CASCADE ON DELETE CASCADE,
        CONSTRAINT uq_aviso_pontos_lote_canal UNIQUE (id_usuario, vence_em, canal),
        CONSTRAINT chk_aviso_pontos_canal CHECK (canal IN ('email', 'whatsapp')),
        CONSTRAINT chk_aviso_pontos_pontos CHECK (pontos > 0)
    )
    """,
    "ALTER TABLE public.aviso_pontos ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.aviso_pontos FORCE ROW LEVEL SECURITY",
    # ---- busca semantica do catalogo ----
    "CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions",
    "ALTER TABLE public.produto ADD COLUMN IF NOT EXISTS embedding "
    f"extensions.vector({DIMENSOES_EMBEDDING})",
    "ALTER TABLE public.produto ADD COLUMN IF NOT EXISTS embedding_em TIMESTAMPTZ",
    "CREATE INDEX IF NOT EXISTS idx_produto_embedding ON public.produto "
    "USING hnsw (embedding extensions.vector_cosine_ops)",
    # ---- horario das lojas ----
    "ALTER TABLE public.loja ADD COLUMN IF NOT EXISTS horario_funcionamento JSONB",
    "ALTER TABLE public.loja DROP CONSTRAINT IF EXISTS chk_loja_horario_objeto",
    "ALTER TABLE public.loja ADD CONSTRAINT chk_loja_horario_objeto "
    "CHECK (horario_funcionamento IS NULL OR jsonb_typeof(horario_funcionamento) = 'object')",
    # ---- conversas dos assistentes ----
    """
    CREATE TABLE IF NOT EXISTS public.conversa_assistente (
        id_conversa UUID NOT NULL DEFAULT gen_random_uuid(),
        id_usuario UUID NOT NULL,
        tipo TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'ativa',
        id_atendimento UUID,
        resumo TEXT,
        criada_em TIMESTAMPTZ NOT NULL DEFAULT now(),
        atualizada_em TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT pk_conversa_assistente PRIMARY KEY (id_conversa),
        CONSTRAINT fk_conversa_assistente_usuario FOREIGN KEY (id_usuario)
            REFERENCES public.usuario (id_usuario) ON UPDATE CASCADE ON DELETE CASCADE,
        CONSTRAINT fk_conversa_assistente_atendimento FOREIGN KEY (id_atendimento)
            REFERENCES public.atendimento (id_atendimento) ON UPDATE CASCADE ON DELETE SET NULL,
        CONSTRAINT chk_conversa_assistente_tipo CHECK (tipo IN ('cliente', 'interno')),
        CONSTRAINT chk_conversa_assistente_status
            CHECK (status IN ('ativa', 'com_atendente', 'encerrada')),
        CONSTRAINT chk_conversa_assistente_passagem
            CHECK (status <> 'com_atendente' OR id_atendimento IS NOT NULL)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_conversa_assistente_usuario "
    "ON public.conversa_assistente (id_usuario, atualizada_em DESC)",
    "CREATE INDEX IF NOT EXISTS idx_conversa_assistente_atendimento "
    "ON public.conversa_assistente (id_atendimento) WHERE id_atendimento IS NOT NULL",
    "ALTER TABLE public.conversa_assistente ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.conversa_assistente FORCE ROW LEVEL SECURITY",
    """
    CREATE TABLE IF NOT EXISTS public.mensagem_assistente (
        id_mensagem UUID NOT NULL DEFAULT gen_random_uuid(),
        id_conversa UUID NOT NULL,
        autor TEXT NOT NULL,
        texto TEXT NOT NULL DEFAULT '',
        ferramenta TEXT,
        dados JSONB,
        sem_resposta BOOLEAN NOT NULL DEFAULT false,
        modelo TEXT,
        tokens_entrada INTEGER,
        tokens_saida INTEGER,
        criada_em TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT pk_mensagem_assistente PRIMARY KEY (id_mensagem),
        CONSTRAINT fk_mensagem_assistente_conversa FOREIGN KEY (id_conversa)
            REFERENCES public.conversa_assistente (id_conversa) ON UPDATE CASCADE ON DELETE CASCADE,
        CONSTRAINT chk_mensagem_assistente_autor
            CHECK (autor IN ('usuario', 'assistente', 'ferramenta')),
        CONSTRAINT chk_mensagem_assistente_ferramenta
            CHECK (autor <> 'ferramenta' OR ferramenta IS NOT NULL),
        CONSTRAINT chk_mensagem_assistente_tokens
            CHECK (COALESCE(tokens_entrada, 0) >= 0 AND COALESCE(tokens_saida, 0) >= 0)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_mensagem_assistente_conversa "
    "ON public.mensagem_assistente (id_conversa, criada_em)",
    "CREATE INDEX IF NOT EXISTS idx_mensagem_assistente_sem_resposta "
    "ON public.mensagem_assistente (criada_em DESC) WHERE sem_resposta",
    "ALTER TABLE public.mensagem_assistente ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.mensagem_assistente FORCE ROW LEVEL SECURITY",
)

DESCIDA = (
    "DROP TABLE IF EXISTS public.mensagem_assistente",
    "DROP TABLE IF EXISTS public.conversa_assistente",
    "ALTER TABLE public.loja DROP CONSTRAINT IF EXISTS chk_loja_horario_objeto",
    "ALTER TABLE public.loja DROP COLUMN IF EXISTS horario_funcionamento",
    "DROP INDEX IF EXISTS public.idx_produto_embedding",
    "ALTER TABLE public.produto DROP COLUMN IF EXISTS embedding_em",
    "ALTER TABLE public.produto DROP COLUMN IF EXISTS embedding",
    # A extensao vector fica: outros objetos do projeto podem passar a depender dela.
    "DROP TABLE IF EXISTS public.aviso_pontos",
    "ALTER TABLE public.usuario DROP CONSTRAINT IF EXISTS chk_usuario_aceita_mensagens_origem",
    "ALTER TABLE public.usuario DROP COLUMN IF EXISTS aceita_mensagens_em",
    "ALTER TABLE public.usuario DROP COLUMN IF EXISTS aceita_mensagens_origem",
    "ALTER TABLE public.usuario DROP COLUMN IF EXISTS aceita_mensagens",
)


def upgrade() -> None:
    for comando in SUBIDA:
        op.execute(comando)


def downgrade() -> None:
    for comando in DESCIDA:
        op.execute(comando)
