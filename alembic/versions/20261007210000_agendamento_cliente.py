"""cliente: agendamento estruturado ligado ao atendimento

Revision ID: 20261007210000
Revises: 20261007200000
Create Date: 2026-10-07 21:00:00

O cliente continua abrindo um atendimento real, mas os dados de prova/ajuste deixam de ficar
soltos no texto da mensagem: loja, data, horario, tipo e contato ficam na tabela
`agendamento_cliente`. A tabela `agenda_horario` controla quais horarios o front pode oferecer.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261007210000"
down_revision: str | Sequence[str] | None = "20261007200000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO categoria_atendimento (codigo, nome, descricao, ordem)
        VALUES ('agendamento', 'Agendamento', 'Provas e ajustes marcados pelo cliente', 15)
        ON CONFLICT (codigo) DO UPDATE
        SET nome = EXCLUDED.nome,
            descricao = EXCLUDED.descricao,
            ordem = LEAST(categoria_atendimento.ordem, EXCLUDED.ordem),
            ativo = true
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agenda_horario (
            id_agenda_horario UUID NOT NULL DEFAULT gen_random_uuid(),
            id_loja UUID NOT NULL,
            dia_semana SMALLINT NOT NULL,
            horario TIME NOT NULL,
            capacidade INTEGER NOT NULL DEFAULT 2,
            ativo BOOLEAN NOT NULL DEFAULT true,
            criado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_agenda_horario PRIMARY KEY (id_agenda_horario),
            CONSTRAINT fk_agenda_horario_loja FOREIGN KEY (id_loja)
                REFERENCES loja (id_loja) ON UPDATE CASCADE ON DELETE CASCADE,
            CONSTRAINT uq_agenda_horario_loja_dia_hora UNIQUE (id_loja, dia_semana, horario),
            CONSTRAINT chk_agenda_horario_dia CHECK (dia_semana BETWEEN 1 AND 6),
            CONSTRAINT chk_agenda_horario_capacidade CHECK (capacidade > 0)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agendamento_cliente (
            id_agendamento UUID NOT NULL DEFAULT gen_random_uuid(),
            id_atendimento UUID NOT NULL,
            id_cliente UUID NOT NULL,
            id_loja UUID NOT NULL,
            tipo TEXT NOT NULL,
            data DATE NOT NULL,
            horario TIME NOT NULL,
            nome_contato TEXT NOT NULL,
            telefone_contato TEXT NOT NULL,
            peca_sku TEXT,
            peca_nome TEXT,
            observacao TEXT,
            criado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_agendamento_cliente PRIMARY KEY (id_agendamento),
            CONSTRAINT uq_agendamento_cliente_atendimento UNIQUE (id_atendimento),
            CONSTRAINT fk_agendamento_cliente_atendimento FOREIGN KEY (id_atendimento)
                REFERENCES atendimento (id_atendimento) ON UPDATE CASCADE ON DELETE CASCADE,
            CONSTRAINT fk_agendamento_cliente_cliente FOREIGN KEY (id_cliente)
                REFERENCES usuario (id_usuario) ON UPDATE CASCADE ON DELETE CASCADE,
            CONSTRAINT fk_agendamento_cliente_loja FOREIGN KEY (id_loja)
                REFERENCES loja (id_loja) ON UPDATE CASCADE ON DELETE RESTRICT,
            CONSTRAINT chk_agendamento_cliente_tipo CHECK (tipo IN ('ajuste', 'prova')),
            CONSTRAINT chk_agendamento_cliente_nome CHECK (length(btrim(nome_contato)) > 0),
            CONSTRAINT chk_agendamento_cliente_telefone CHECK (length(btrim(telefone_contato)) > 0)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agendamento_cliente_loja_data "
        "ON agendamento_cliente (id_loja, data, horario)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agendamento_cliente_cliente "
        "ON agendamento_cliente (id_cliente, criado_em DESC)"
    )
    op.execute(
        """
        INSERT INTO agenda_horario (id_loja, dia_semana, horario, capacidade)
        SELECT l.id_loja, d.dia_semana, h.horario::time, 2
        FROM loja l
        CROSS JOIN (VALUES (1), (2), (3), (4), (5), (6)) AS d(dia_semana)
        CROSS JOIN (VALUES ('10:00'), ('11:30'), ('14:00'), ('15:30'), ('17:00'), ('18:30')) AS h(horario)
        WHERE l.ativa IS TRUE
        ON CONFLICT (id_loja, dia_semana, horario) DO NOTHING
        """
    )
    op.execute("ALTER TABLE agenda_horario ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agenda_horario FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agendamento_cliente ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agendamento_cliente FORCE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON agenda_horario, agendamento_cliente FROM anon, authenticated")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agendamento_cliente")
    op.execute("DROP TABLE IF EXISTS agenda_horario")
    op.execute(
        """
        DELETE FROM categoria_atendimento c
        WHERE c.codigo = 'agendamento'
          AND NOT EXISTS (
              SELECT 1 FROM atendimento a
              WHERE a.id_categoria_atendimento = c.id_categoria_atendimento
          )
        """
    )
