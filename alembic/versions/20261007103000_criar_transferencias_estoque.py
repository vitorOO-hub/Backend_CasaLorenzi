"""cria fluxo de transferencias e reposicoes de estoque

Revision ID: 20261007103000
Revises: 20261007000600
Create Date: 2026-10-07 10:30:00
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20261007103000"
down_revision: str | Sequence[str] | None = "20261007000600"
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
        CREATE TABLE IF NOT EXISTS tipo_transferencia_estoque (
            id_tipo_transferencia_estoque UUID NOT NULL DEFAULT gen_random_uuid(),
            codigo TEXT NOT NULL,
            nome TEXT NOT NULL,
            descricao TEXT,
            ativo BOOLEAN NOT NULL DEFAULT TRUE,
            ordem INTEGER NOT NULL DEFAULT 0,

            CONSTRAINT pk_tipo_transferencia_estoque PRIMARY KEY (id_tipo_transferencia_estoque),
            CONSTRAINT uq_tipo_transferencia_estoque_codigo UNIQUE (codigo),
            CONSTRAINT uq_tipo_transferencia_estoque_nome UNIQUE (nome),
            CONSTRAINT chk_tipo_transferencia_estoque_codigo_nao_vazio CHECK (length(trim(codigo)) > 0),
            CONSTRAINT chk_tipo_transferencia_estoque_nome_nao_vazio CHECK (length(trim(nome)) > 0),
            CONSTRAINT chk_tipo_transferencia_estoque_ordem_nao_negativa CHECK (ordem >= 0)
        );

        INSERT INTO tipo_transferencia_estoque (codigo, nome, descricao, ordem)
        VALUES
            ('transferencia', 'Transferencia entre lojas', 'Pedido de uma loja para outra loja da rede.', 1),
            ('reposicao_rede', 'Reposicao a rede', 'Pedido de reposicao para a rede.', 2)
        ON CONFLICT (codigo) DO UPDATE
        SET nome = EXCLUDED.nome,
            descricao = EXCLUDED.descricao,
            ordem = EXCLUDED.ordem,
            ativo = TRUE;

        CREATE TABLE IF NOT EXISTS status_transferencia_estoque (
            id_status_transferencia_estoque UUID NOT NULL DEFAULT gen_random_uuid(),
            codigo TEXT NOT NULL,
            nome TEXT NOT NULL,
            descricao TEXT,
            ativo BOOLEAN NOT NULL DEFAULT TRUE,
            ordem INTEGER NOT NULL DEFAULT 0,

            CONSTRAINT pk_status_transferencia_estoque PRIMARY KEY (id_status_transferencia_estoque),
            CONSTRAINT uq_status_transferencia_estoque_codigo UNIQUE (codigo),
            CONSTRAINT uq_status_transferencia_estoque_nome UNIQUE (nome),
            CONSTRAINT chk_status_transferencia_estoque_codigo_nao_vazio CHECK (length(trim(codigo)) > 0),
            CONSTRAINT chk_status_transferencia_estoque_nome_nao_vazio CHECK (length(trim(nome)) > 0),
            CONSTRAINT chk_status_transferencia_estoque_ordem_nao_negativa CHECK (ordem >= 0)
        );

        INSERT INTO status_transferencia_estoque (codigo, nome, descricao, ordem)
        VALUES
            ('solicitada', 'Solicitada', 'Transferencia ou reposicao solicitada pelo operador.', 1),
            ('aceita', 'Aceita', 'Transferencia aceita pela loja de origem.', 2)
        ON CONFLICT (codigo) DO UPDATE
        SET nome = EXCLUDED.nome,
            descricao = EXCLUDED.descricao,
            ordem = EXCLUDED.ordem,
            ativo = TRUE;

        CREATE TABLE IF NOT EXISTS transferencia_estoque (
            id_transferencia_estoque UUID NOT NULL DEFAULT gen_random_uuid(),
            id_tipo_transferencia_estoque UUID NOT NULL,
            id_status_transferencia_estoque UUID NOT NULL,
            id_loja_origem UUID,
            id_loja_destino UUID NOT NULL,
            id_variacao UUID NOT NULL,
            id_usuario_solicitante UUID NOT NULL,
            id_usuario_responsavel UUID,
            quantidade INTEGER NOT NULL,
            observacao TEXT,
            solicitada_em TIMESTAMPTZ NOT NULL DEFAULT now(),
            aceita_em TIMESTAMPTZ,
            atualizada_em TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT pk_transferencia_estoque PRIMARY KEY (id_transferencia_estoque),
            CONSTRAINT fk_transferencia_estoque_tipo
                FOREIGN KEY (id_tipo_transferencia_estoque)
                REFERENCES tipo_transferencia_estoque (id_tipo_transferencia_estoque)
                ON UPDATE CASCADE
                ON DELETE RESTRICT,
            CONSTRAINT fk_transferencia_estoque_status
                FOREIGN KEY (id_status_transferencia_estoque)
                REFERENCES status_transferencia_estoque (id_status_transferencia_estoque)
                ON UPDATE CASCADE
                ON DELETE RESTRICT,
            CONSTRAINT fk_transferencia_estoque_loja_origem
                FOREIGN KEY (id_loja_origem)
                REFERENCES loja (id_loja)
                ON UPDATE CASCADE
                ON DELETE RESTRICT,
            CONSTRAINT fk_transferencia_estoque_loja_destino
                FOREIGN KEY (id_loja_destino)
                REFERENCES loja (id_loja)
                ON UPDATE CASCADE
                ON DELETE RESTRICT,
            CONSTRAINT fk_transferencia_estoque_variacao
                FOREIGN KEY (id_variacao)
                REFERENCES variacao_produto (id_variacao)
                ON UPDATE CASCADE
                ON DELETE RESTRICT,
            CONSTRAINT fk_transferencia_estoque_usuario_solicitante
                FOREIGN KEY (id_usuario_solicitante)
                REFERENCES usuario (id_usuario)
                ON UPDATE CASCADE
                ON DELETE RESTRICT,
            CONSTRAINT fk_transferencia_estoque_usuario_responsavel
                FOREIGN KEY (id_usuario_responsavel)
                REFERENCES usuario (id_usuario)
                ON UPDATE CASCADE
                ON DELETE RESTRICT,
            CONSTRAINT chk_transferencia_estoque_quantidade_positiva CHECK (quantidade > 0),
            CONSTRAINT chk_transferencia_estoque_lojas_diferentes CHECK (
                id_loja_origem IS NULL OR id_loja_origem <> id_loja_destino
            )
        );

        CREATE INDEX IF NOT EXISTS idx_transferencia_estoque_id_tipo
            ON transferencia_estoque (id_tipo_transferencia_estoque);
        CREATE INDEX IF NOT EXISTS idx_transferencia_estoque_id_status
            ON transferencia_estoque (id_status_transferencia_estoque);
        CREATE INDEX IF NOT EXISTS idx_transferencia_estoque_id_loja_origem
            ON transferencia_estoque (id_loja_origem);
        CREATE INDEX IF NOT EXISTS idx_transferencia_estoque_id_loja_destino
            ON transferencia_estoque (id_loja_destino);
        CREATE INDEX IF NOT EXISTS idx_transferencia_estoque_id_variacao
            ON transferencia_estoque (id_variacao);
        CREATE INDEX IF NOT EXISTS idx_transferencia_estoque_id_usuario_solicitante
            ON transferencia_estoque (id_usuario_solicitante);
        CREATE INDEX IF NOT EXISTS idx_transferencia_estoque_id_usuario_responsavel
            ON transferencia_estoque (id_usuario_responsavel);
        CREATE INDEX IF NOT EXISTS idx_transferencia_estoque_solicitada_em
            ON transferencia_estoque (solicitada_em);
        """
    )


def downgrade() -> None:
    executar_bloco(
        """
        DROP TABLE IF EXISTS transferencia_estoque CASCADE;
        DROP TABLE IF EXISTS status_transferencia_estoque CASCADE;
        DROP TABLE IF EXISTS tipo_transferencia_estoque CASCADE;
        """
    )
