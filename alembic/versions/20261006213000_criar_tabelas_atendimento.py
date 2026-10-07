"""cria tabelas de atendimento, mensagens e avaliacoes

Revision ID: 20261006213000
Revises: 20261005000000
Create Date: 2026-10-06 21:30:00
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20261006213000"
down_revision: str | Sequence[str] | None = "20261005000000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def executar_bloco(sql: str) -> None:
    for comando in sql.split(";"):
        comando = comando.strip()
        if comando:
            op.execute(comando)


def upgrade() -> None:
    executar_bloco(
        """
        CREATE TABLE IF NOT EXISTS status_atendimento (
            id_status_atendimento UUID NOT NULL DEFAULT gen_random_uuid(),
            codigo TEXT NOT NULL,
            nome TEXT NOT NULL,
            descricao TEXT,
            ativo BOOLEAN NOT NULL DEFAULT TRUE,
            ordem INTEGER NOT NULL DEFAULT 0,

            CONSTRAINT pk_status_atendimento PRIMARY KEY (id_status_atendimento),
            CONSTRAINT uq_status_atendimento_codigo UNIQUE (codigo),
            CONSTRAINT uq_status_atendimento_nome UNIQUE (nome),
            CONSTRAINT chk_status_atendimento_codigo_nao_vazio CHECK (length(trim(codigo)) > 0),
            CONSTRAINT chk_status_atendimento_nome_nao_vazio CHECK (length(trim(nome)) > 0),
            CONSTRAINT chk_status_atendimento_ordem_nao_negativa CHECK (ordem >= 0)
        );

        INSERT INTO status_atendimento (codigo, nome, descricao, ordem)
        VALUES
            ('aberto', 'Aberto', 'Atendimento criado e ainda nao assumido.', 1),
            ('em_andamento', 'Em andamento', 'Atendimento assumido por um atendente ou gerente.', 2),
            ('aguardando_cliente', 'Aguardando cliente', 'Atendimento depende de resposta do cliente.', 3),
            ('resolvido', 'Resolvido', 'Solicitacao resolvida, aguardando encerramento.', 4),
            ('encerrado', 'Encerrado', 'Atendimento finalizado.', 5),
            ('cancelado', 'Cancelado', 'Atendimento cancelado.', 6)
        ON CONFLICT (codigo) DO UPDATE
        SET nome = EXCLUDED.nome,
            descricao = EXCLUDED.descricao,
            ordem = EXCLUDED.ordem,
            ativo = TRUE;

        CREATE TABLE IF NOT EXISTS categoria_atendimento (
            id_categoria_atendimento UUID NOT NULL DEFAULT gen_random_uuid(),
            codigo TEXT NOT NULL,
            nome TEXT NOT NULL,
            descricao TEXT,
            ativo BOOLEAN NOT NULL DEFAULT TRUE,
            ordem INTEGER NOT NULL DEFAULT 0,

            CONSTRAINT pk_categoria_atendimento PRIMARY KEY (id_categoria_atendimento),
            CONSTRAINT uq_categoria_atendimento_codigo UNIQUE (codigo),
            CONSTRAINT uq_categoria_atendimento_nome UNIQUE (nome),
            CONSTRAINT chk_categoria_atendimento_codigo_nao_vazio CHECK (length(trim(codigo)) > 0),
            CONSTRAINT chk_categoria_atendimento_nome_nao_vazio CHECK (length(trim(nome)) > 0),
            CONSTRAINT chk_categoria_atendimento_ordem_nao_negativa CHECK (ordem >= 0)
        );

        INSERT INTO categoria_atendimento (codigo, nome, descricao, ordem)
        VALUES
            ('pedido', 'Pedido', 'Duvidas ou problemas relacionados a pedido.', 1),
            ('produto', 'Produto', 'Duvidas sobre produto, tamanho, cor ou disponibilidade.', 2),
            ('entrega', 'Entrega', 'Duvidas ou problemas de entrega ou retirada.', 3),
            ('pagamento', 'Pagamento', 'Duvidas ou problemas de pagamento.', 4),
            ('troca_devolucao', 'Troca ou devolucao', 'Solicitacoes de troca, devolucao ou pos-venda.', 5),
            ('outro', 'Outro', 'Atendimento fora das categorias principais.', 6)
        ON CONFLICT (codigo) DO UPDATE
        SET nome = EXCLUDED.nome,
            descricao = EXCLUDED.descricao,
            ordem = EXCLUDED.ordem,
            ativo = TRUE;

        CREATE TABLE IF NOT EXISTS canal_atendimento (
            id_canal_atendimento UUID NOT NULL DEFAULT gen_random_uuid(),
            codigo TEXT NOT NULL,
            nome TEXT NOT NULL,
            descricao TEXT,
            ativo BOOLEAN NOT NULL DEFAULT TRUE,
            ordem INTEGER NOT NULL DEFAULT 0,

            CONSTRAINT pk_canal_atendimento PRIMARY KEY (id_canal_atendimento),
            CONSTRAINT uq_canal_atendimento_codigo UNIQUE (codigo),
            CONSTRAINT uq_canal_atendimento_nome UNIQUE (nome),
            CONSTRAINT chk_canal_atendimento_codigo_nao_vazio CHECK (length(trim(codigo)) > 0),
            CONSTRAINT chk_canal_atendimento_nome_nao_vazio CHECK (length(trim(nome)) > 0),
            CONSTRAINT chk_canal_atendimento_ordem_nao_negativa CHECK (ordem >= 0)
        );

        INSERT INTO canal_atendimento (codigo, nome, descricao, ordem)
        VALUES
            ('site', 'Site', 'Atendimento aberto pelo site ou portal do cliente.', 1),
            ('whatsapp', 'WhatsApp', 'Atendimento iniciado pelo WhatsApp.', 2),
            ('email', 'E-mail', 'Atendimento iniciado por e-mail.', 3),
            ('telefone', 'Telefone', 'Atendimento iniciado por telefone.', 4),
            ('presencial', 'Presencial', 'Atendimento iniciado em loja fisica.', 5)
        ON CONFLICT (codigo) DO UPDATE
        SET nome = EXCLUDED.nome,
            descricao = EXCLUDED.descricao,
            ordem = EXCLUDED.ordem,
            ativo = TRUE;

        CREATE TABLE IF NOT EXISTS prioridade_atendimento (
            id_prioridade_atendimento UUID NOT NULL DEFAULT gen_random_uuid(),
            codigo TEXT NOT NULL,
            nome TEXT NOT NULL,
            descricao TEXT,
            ativo BOOLEAN NOT NULL DEFAULT TRUE,
            ordem INTEGER NOT NULL DEFAULT 0,

            CONSTRAINT pk_prioridade_atendimento PRIMARY KEY (id_prioridade_atendimento),
            CONSTRAINT uq_prioridade_atendimento_codigo UNIQUE (codigo),
            CONSTRAINT uq_prioridade_atendimento_nome UNIQUE (nome),
            CONSTRAINT chk_prioridade_atendimento_codigo_nao_vazio CHECK (length(trim(codigo)) > 0),
            CONSTRAINT chk_prioridade_atendimento_nome_nao_vazio CHECK (length(trim(nome)) > 0),
            CONSTRAINT chk_prioridade_atendimento_ordem_nao_negativa CHECK (ordem >= 0)
        );

        INSERT INTO prioridade_atendimento (codigo, nome, descricao, ordem)
        VALUES
            ('baixa', 'Baixa', 'Atendimento sem urgencia operacional.', 1),
            ('media', 'Media', 'Atendimento com prioridade padrao.', 2),
            ('alta', 'Alta', 'Atendimento importante para a experiencia do cliente.', 3),
            ('urgente', 'Urgente', 'Atendimento critico que exige resposta rapida.', 4)
        ON CONFLICT (codigo) DO UPDATE
        SET nome = EXCLUDED.nome,
            descricao = EXCLUDED.descricao,
            ordem = EXCLUDED.ordem,
            ativo = TRUE;

        CREATE TABLE IF NOT EXISTS atendimento (
            id_atendimento UUID NOT NULL DEFAULT gen_random_uuid(),
            id_cliente UUID NOT NULL,
            id_usuario_responsavel UUID,
            id_pedido UUID,
            id_canal_atendimento UUID NOT NULL,
            id_categoria_atendimento UUID NOT NULL,
            id_prioridade_atendimento UUID NOT NULL,
            id_status_atendimento UUID NOT NULL,
            aberto_em TIMESTAMPTZ NOT NULL DEFAULT now(),
            encerrado_em TIMESTAMPTZ,
            atualizado_em TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT pk_atendimento PRIMARY KEY (id_atendimento),
            CONSTRAINT fk_atendimento_cliente
                FOREIGN KEY (id_cliente)
                REFERENCES usuario (id_usuario)
                ON UPDATE CASCADE
                ON DELETE RESTRICT,
            CONSTRAINT fk_atendimento_usuario_responsavel
                FOREIGN KEY (id_usuario_responsavel)
                REFERENCES usuario (id_usuario)
                ON UPDATE CASCADE
                ON DELETE RESTRICT,
            CONSTRAINT fk_atendimento_pedido
                FOREIGN KEY (id_pedido)
                REFERENCES pedido (id_pedido)
                ON UPDATE CASCADE
                ON DELETE RESTRICT,
            CONSTRAINT fk_atendimento_canal
                FOREIGN KEY (id_canal_atendimento)
                REFERENCES canal_atendimento (id_canal_atendimento)
                ON UPDATE CASCADE
                ON DELETE RESTRICT,
            CONSTRAINT fk_atendimento_categoria
                FOREIGN KEY (id_categoria_atendimento)
                REFERENCES categoria_atendimento (id_categoria_atendimento)
                ON UPDATE CASCADE
                ON DELETE RESTRICT,
            CONSTRAINT fk_atendimento_prioridade
                FOREIGN KEY (id_prioridade_atendimento)
                REFERENCES prioridade_atendimento (id_prioridade_atendimento)
                ON UPDATE CASCADE
                ON DELETE RESTRICT,
            CONSTRAINT fk_atendimento_status
                FOREIGN KEY (id_status_atendimento)
                REFERENCES status_atendimento (id_status_atendimento)
                ON UPDATE CASCADE
                ON DELETE RESTRICT,
            CONSTRAINT chk_atendimento_datas CHECK (
                encerrado_em IS NULL OR encerrado_em >= aberto_em
            )
        );

        CREATE TABLE IF NOT EXISTS atendimento_item (
            id_atendimento_item UUID NOT NULL DEFAULT gen_random_uuid(),
            id_atendimento UUID NOT NULL,
            id_item_pedido UUID NOT NULL,

            CONSTRAINT pk_atendimento_item PRIMARY KEY (id_atendimento_item),
            CONSTRAINT fk_atendimento_item_atendimento
                FOREIGN KEY (id_atendimento)
                REFERENCES atendimento (id_atendimento)
                ON UPDATE CASCADE
                ON DELETE RESTRICT,
            CONSTRAINT fk_atendimento_item_item_pedido
                FOREIGN KEY (id_item_pedido)
                REFERENCES item_pedido (id_item_pedido)
                ON UPDATE CASCADE
                ON DELETE RESTRICT,
            CONSTRAINT uq_atendimento_item_atendimento_item UNIQUE (id_atendimento, id_item_pedido)
        );

        CREATE TABLE IF NOT EXISTS mensagem (
            id_mensagem UUID NOT NULL DEFAULT gen_random_uuid(),
            id_atendimento UUID NOT NULL,
            id_usuario_remetente UUID NOT NULL,
            texto TEXT NOT NULL,
            anexo_url TEXT,
            enviada_em TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT pk_mensagem PRIMARY KEY (id_mensagem),
            CONSTRAINT fk_mensagem_atendimento
                FOREIGN KEY (id_atendimento)
                REFERENCES atendimento (id_atendimento)
                ON UPDATE CASCADE
                ON DELETE RESTRICT,
            CONSTRAINT fk_mensagem_usuario_remetente
                FOREIGN KEY (id_usuario_remetente)
                REFERENCES usuario (id_usuario)
                ON UPDATE CASCADE
                ON DELETE RESTRICT,
            CONSTRAINT chk_mensagem_texto_nao_vazio CHECK (length(trim(texto)) > 0)
        );

        CREATE TABLE IF NOT EXISTS avaliacao_atendimento (
            id_avaliacao UUID NOT NULL DEFAULT gen_random_uuid(),
            id_atendimento UUID NOT NULL,
            nota SMALLINT NOT NULL,
            comentario TEXT,
            criada_em TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT pk_avaliacao_atendimento PRIMARY KEY (id_avaliacao),
            CONSTRAINT fk_avaliacao_atendimento_atendimento
                FOREIGN KEY (id_atendimento)
                REFERENCES atendimento (id_atendimento)
                ON UPDATE CASCADE
                ON DELETE RESTRICT,
            CONSTRAINT uq_avaliacao_atendimento_atendimento UNIQUE (id_atendimento),
            CONSTRAINT chk_avaliacao_atendimento_nota CHECK (nota BETWEEN 1 AND 5)
        );

        CREATE INDEX IF NOT EXISTS idx_atendimento_id_cliente ON atendimento (id_cliente);
        CREATE INDEX IF NOT EXISTS idx_atendimento_id_usuario_responsavel ON atendimento (id_usuario_responsavel);
        CREATE INDEX IF NOT EXISTS idx_atendimento_id_pedido ON atendimento (id_pedido);
        CREATE INDEX IF NOT EXISTS idx_atendimento_id_canal ON atendimento (id_canal_atendimento);
        CREATE INDEX IF NOT EXISTS idx_atendimento_id_categoria ON atendimento (id_categoria_atendimento);
        CREATE INDEX IF NOT EXISTS idx_atendimento_id_prioridade ON atendimento (id_prioridade_atendimento);
        CREATE INDEX IF NOT EXISTS idx_atendimento_id_status ON atendimento (id_status_atendimento);
        CREATE INDEX IF NOT EXISTS idx_atendimento_aberto_em ON atendimento (aberto_em);

        CREATE INDEX IF NOT EXISTS idx_atendimento_item_id_item_pedido ON atendimento_item (id_item_pedido);
        CREATE INDEX IF NOT EXISTS idx_mensagem_id_atendimento ON mensagem (id_atendimento);
        CREATE INDEX IF NOT EXISTS idx_mensagem_id_usuario_remetente ON mensagem (id_usuario_remetente);
        CREATE INDEX IF NOT EXISTS idx_mensagem_enviada_em ON mensagem (enviada_em);
        CREATE INDEX IF NOT EXISTS idx_avaliacao_atendimento_id_atendimento ON avaliacao_atendimento (id_atendimento);
        """
    )


def downgrade() -> None:
    executar_bloco(
        """
        DROP TABLE IF EXISTS avaliacao_atendimento CASCADE;
        DROP TABLE IF EXISTS mensagem CASCADE;
        DROP TABLE IF EXISTS atendimento_item CASCADE;
        DROP TABLE IF EXISTS atendimento CASCADE;
        DROP TABLE IF EXISTS prioridade_atendimento CASCADE;
        DROP TABLE IF EXISTS canal_atendimento CASCADE;
        DROP TABLE IF EXISTS categoria_atendimento CASCADE;
        DROP TABLE IF EXISTS status_atendimento CASCADE;
        """
    )
