BEGIN;

CREATE TABLE loja (
    id_loja BIGINT GENERATED ALWAYS AS IDENTITY,
    codigo TEXT NOT NULL,
    nome TEXT NOT NULL,
    cnpj TEXT,
    email TEXT,
    telefone TEXT,
    endereco TEXT,
    cidade TEXT,
    uf TEXT,
    ativa BOOLEAN NOT NULL DEFAULT TRUE,
    criada_em TIMESTAMPTZ NOT NULL DEFAULT now(),
    atualizada_em TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT pk_loja PRIMARY KEY (id_loja),
    CONSTRAINT uq_loja_codigo UNIQUE (codigo),
    CONSTRAINT uq_loja_cnpj UNIQUE (cnpj),
    CONSTRAINT chk_loja_codigo_nao_vazio CHECK (length(trim(codigo)) > 0),
    CONSTRAINT chk_loja_nome_nao_vazio CHECK (length(trim(nome)) > 0),
    CONSTRAINT chk_loja_uf CHECK (uf IS NULL OR (length(uf) = 2 AND uf = upper(uf)))
);

CREATE TABLE tipo_usuario (
    id_tipo_usuario BIGINT GENERATED ALWAYS AS IDENTITY,
    codigo TEXT NOT NULL,
    nome TEXT NOT NULL,
    descricao TEXT,
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    ordem INTEGER NOT NULL DEFAULT 0,

    CONSTRAINT pk_tipo_usuario PRIMARY KEY (id_tipo_usuario),
    CONSTRAINT uq_tipo_usuario_codigo UNIQUE (codigo),
    CONSTRAINT uq_tipo_usuario_nome UNIQUE (nome),
    CONSTRAINT chk_tipo_usuario_codigo_nao_vazio CHECK (length(trim(codigo)) > 0),
    CONSTRAINT chk_tipo_usuario_nome_nao_vazio CHECK (length(trim(nome)) > 0),
    CONSTRAINT chk_tipo_usuario_ordem_nao_negativa CHECK (ordem >= 0)
);

INSERT INTO tipo_usuario (codigo, nome, descricao, ordem)
VALUES
    ('cliente', 'Cliente', 'Usuario que compra produtos na loja ou no e-commerce.', 1),
    ('operador_estoque', 'Operador de estoque', 'Usuario responsavel por entradas, saidas e ajustes de estoque.', 2),
    ('atendente', 'Atendente', 'Usuario responsavel por atendimento e apoio a vendas.', 3),
    ('gerente_loja', 'Gerente da loja', 'Usuario responsavel pela gestao de uma loja.', 4),
    ('diretor', 'Diretor', 'Usuario com visao administrativa geral.', 5);

CREATE TABLE usuario (
    id_usuario BIGINT GENERATED ALWAYS AS IDENTITY,
    id_tipo_usuario BIGINT NOT NULL,
    id_loja BIGINT,
    auth_user_id UUID,
    nome TEXT NOT NULL,
    email TEXT NOT NULL,
    telefone TEXT,
    documento TEXT,
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT pk_usuario PRIMARY KEY (id_usuario),
    CONSTRAINT fk_usuario_tipo_usuario
        FOREIGN KEY (id_tipo_usuario)
        REFERENCES tipo_usuario (id_tipo_usuario)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    CONSTRAINT fk_usuario_loja
        FOREIGN KEY (id_loja)
        REFERENCES loja (id_loja)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    CONSTRAINT uq_usuario_auth_user_id UNIQUE (auth_user_id),
    CONSTRAINT uq_usuario_email UNIQUE (email),
    CONSTRAINT uq_usuario_documento UNIQUE (documento),
    CONSTRAINT chk_usuario_nome_nao_vazio CHECK (length(trim(nome)) > 0),
    CONSTRAINT chk_usuario_email_nao_vazio CHECK (length(trim(email)) > 0)
);

CREATE TABLE produto (
    id_produto BIGINT GENERATED ALWAYS AS IDENTITY,
    nome TEXT NOT NULL,
    marca TEXT,
    categoria TEXT,
    descricao TEXT,
    preco_base DECIMAL(12,2) NOT NULL,
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT pk_produto PRIMARY KEY (id_produto),
    CONSTRAINT uq_produto_nome_marca UNIQUE (nome, marca),
    CONSTRAINT chk_produto_nome_nao_vazio CHECK (length(trim(nome)) > 0),
    CONSTRAINT chk_produto_preco_base CHECK (preco_base >= 0)
);

CREATE TABLE variacao_produto (
    id_variacao BIGINT GENERATED ALWAYS AS IDENTITY,
    id_produto BIGINT NOT NULL,
    sku TEXT NOT NULL,
    cor TEXT NOT NULL,
    tamanho TEXT NOT NULL,
    preco_venda DECIMAL(12,2) NOT NULL,
    ativa BOOLEAN NOT NULL DEFAULT TRUE,
    criada_em TIMESTAMPTZ NOT NULL DEFAULT now(),
    atualizada_em TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT pk_variacao_produto PRIMARY KEY (id_variacao),
    CONSTRAINT fk_variacao_produto_produto
        FOREIGN KEY (id_produto)
        REFERENCES produto (id_produto)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    CONSTRAINT uq_variacao_produto_sku UNIQUE (sku),
    CONSTRAINT uq_variacao_produto_grade UNIQUE (id_produto, cor, tamanho),
    CONSTRAINT chk_variacao_produto_sku_nao_vazio CHECK (length(trim(sku)) > 0),
    CONSTRAINT chk_variacao_produto_cor_nao_vazia CHECK (length(trim(cor)) > 0),
    CONSTRAINT chk_variacao_produto_tamanho_nao_vazio CHECK (length(trim(tamanho)) > 0),
    CONSTRAINT chk_variacao_produto_preco_venda CHECK (preco_venda >= 0)
);

CREATE TABLE estoque (
    id_estoque BIGINT GENERATED ALWAYS AS IDENTITY,
    id_loja BIGINT NOT NULL,
    id_variacao BIGINT NOT NULL,
    quantidade INTEGER NOT NULL DEFAULT 0,
    estoque_minimo INTEGER NOT NULL DEFAULT 0,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT pk_estoque PRIMARY KEY (id_estoque),
    CONSTRAINT fk_estoque_loja
        FOREIGN KEY (id_loja)
        REFERENCES loja (id_loja)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    CONSTRAINT fk_estoque_variacao_produto
        FOREIGN KEY (id_variacao)
        REFERENCES variacao_produto (id_variacao)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    CONSTRAINT uq_estoque_loja_variacao UNIQUE (id_loja, id_variacao),
    CONSTRAINT chk_estoque_quantidade_nao_negativa CHECK (quantidade >= 0),
    CONSTRAINT chk_estoque_minimo_nao_negativo CHECK (estoque_minimo >= 0)
);

CREATE TABLE status_pedido (
    id_status_pedido BIGINT GENERATED ALWAYS AS IDENTITY,
    codigo TEXT NOT NULL,
    nome TEXT NOT NULL,
    descricao TEXT,
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    ordem INTEGER NOT NULL DEFAULT 0,

    CONSTRAINT pk_status_pedido PRIMARY KEY (id_status_pedido),
    CONSTRAINT uq_status_pedido_codigo UNIQUE (codigo),
    CONSTRAINT uq_status_pedido_nome UNIQUE (nome),
    CONSTRAINT chk_status_pedido_codigo_nao_vazio CHECK (length(trim(codigo)) > 0),
    CONSTRAINT chk_status_pedido_nome_nao_vazio CHECK (length(trim(nome)) > 0),
    CONSTRAINT chk_status_pedido_ordem_nao_negativa CHECK (ordem >= 0)
);

INSERT INTO status_pedido (codigo, nome, descricao, ordem)
VALUES
    ('criado', 'Criado', 'Pedido criado, ainda sem pagamento aprovado.', 1),
    ('aguardando_pagamento', 'Aguardando pagamento', 'Pedido aguardando confirmacao de pagamento.', 2),
    ('pago', 'Pago', 'Pedido com pagamento aprovado.', 3),
    ('separado', 'Separado', 'Pedido separado para entrega ou retirada.', 4),
    ('entregue', 'Entregue', 'Pedido entregue ao cliente.', 5),
    ('cancelado', 'Cancelado', 'Pedido cancelado.', 6);

CREATE TABLE pedido (
    id_pedido BIGINT GENERATED ALWAYS AS IDENTITY,
    numero_pedido TEXT NOT NULL,
    id_loja BIGINT NOT NULL,
    id_cliente BIGINT NOT NULL,
    id_usuario_responsavel BIGINT,
    id_status_pedido BIGINT NOT NULL,
    valor_total DECIMAL(12,2) NOT NULL DEFAULT 0,
    observacao TEXT,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT pk_pedido PRIMARY KEY (id_pedido),
    CONSTRAINT fk_pedido_loja
        FOREIGN KEY (id_loja)
        REFERENCES loja (id_loja)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    CONSTRAINT fk_pedido_cliente
        FOREIGN KEY (id_cliente)
        REFERENCES usuario (id_usuario)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    CONSTRAINT fk_pedido_usuario_responsavel
        FOREIGN KEY (id_usuario_responsavel)
        REFERENCES usuario (id_usuario)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    CONSTRAINT fk_pedido_status_pedido
        FOREIGN KEY (id_status_pedido)
        REFERENCES status_pedido (id_status_pedido)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    CONSTRAINT uq_pedido_numero_pedido UNIQUE (numero_pedido),
    CONSTRAINT chk_pedido_numero_nao_vazio CHECK (length(trim(numero_pedido)) > 0),
    CONSTRAINT chk_pedido_valor_total_nao_negativo CHECK (valor_total >= 0)
);

CREATE TABLE item_pedido (
    id_item_pedido BIGINT GENERATED ALWAYS AS IDENTITY,
    id_pedido BIGINT NOT NULL,
    id_variacao BIGINT NOT NULL,
    quantidade INTEGER NOT NULL,
    preco_unitario DECIMAL(12,2) NOT NULL,
    valor_total DECIMAL(12,2) GENERATED ALWAYS AS (quantidade::DECIMAL(12,2) * preco_unitario) STORED,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT pk_item_pedido PRIMARY KEY (id_item_pedido),
    CONSTRAINT fk_item_pedido_pedido
        FOREIGN KEY (id_pedido)
        REFERENCES pedido (id_pedido)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    CONSTRAINT fk_item_pedido_variacao_produto
        FOREIGN KEY (id_variacao)
        REFERENCES variacao_produto (id_variacao)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    CONSTRAINT uq_item_pedido_pedido_variacao UNIQUE (id_pedido, id_variacao),
    CONSTRAINT chk_item_pedido_quantidade_positiva CHECK (quantidade > 0),
    CONSTRAINT chk_item_pedido_preco_unitario_nao_negativo CHECK (preco_unitario >= 0)
);

CREATE TABLE metodo_pagamento (
    id_metodo_pagamento BIGINT GENERATED ALWAYS AS IDENTITY,
    codigo TEXT NOT NULL,
    nome TEXT NOT NULL,
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    ordem INTEGER NOT NULL DEFAULT 0,

    CONSTRAINT pk_metodo_pagamento PRIMARY KEY (id_metodo_pagamento),
    CONSTRAINT uq_metodo_pagamento_codigo UNIQUE (codigo),
    CONSTRAINT uq_metodo_pagamento_nome UNIQUE (nome),
    CONSTRAINT chk_metodo_pagamento_codigo_nao_vazio CHECK (length(trim(codigo)) > 0),
    CONSTRAINT chk_metodo_pagamento_nome_nao_vazio CHECK (length(trim(nome)) > 0),
    CONSTRAINT chk_metodo_pagamento_ordem_nao_negativa CHECK (ordem >= 0)
);

INSERT INTO metodo_pagamento (codigo, nome, ordem)
VALUES
    ('cartao_credito', 'Cartao de credito', 1),
    ('cartao_debito', 'Cartao de debito', 2),
    ('pix', 'PIX', 3),
    ('boleto', 'Boleto', 4),
    ('dinheiro', 'Dinheiro', 5);

CREATE TABLE status_pagamento (
    id_status_pagamento BIGINT GENERATED ALWAYS AS IDENTITY,
    codigo TEXT NOT NULL,
    nome TEXT NOT NULL,
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    ordem INTEGER NOT NULL DEFAULT 0,

    CONSTRAINT pk_status_pagamento PRIMARY KEY (id_status_pagamento),
    CONSTRAINT uq_status_pagamento_codigo UNIQUE (codigo),
    CONSTRAINT uq_status_pagamento_nome UNIQUE (nome),
    CONSTRAINT chk_status_pagamento_codigo_nao_vazio CHECK (length(trim(codigo)) > 0),
    CONSTRAINT chk_status_pagamento_nome_nao_vazio CHECK (length(trim(nome)) > 0),
    CONSTRAINT chk_status_pagamento_ordem_nao_negativa CHECK (ordem >= 0)
);

INSERT INTO status_pagamento (codigo, nome, ordem)
VALUES
    ('pendente', 'Pendente', 1),
    ('aprovado', 'Aprovado', 2),
    ('recusado', 'Recusado', 3),
    ('cancelado', 'Cancelado', 4),
    ('estornado', 'Estornado', 5);

CREATE TABLE pagamento (
    id_pagamento BIGINT GENERATED ALWAYS AS IDENTITY,
    id_pedido BIGINT NOT NULL,
    tentativa SMALLINT NOT NULL DEFAULT 1,
    id_metodo_pagamento BIGINT NOT NULL,
    id_status_pagamento BIGINT NOT NULL,
    valor DECIMAL(12,2) NOT NULL,
    transacao_externa_id TEXT,
    processado_em TIMESTAMPTZ,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT pk_pagamento PRIMARY KEY (id_pagamento),
    CONSTRAINT fk_pagamento_pedido
        FOREIGN KEY (id_pedido)
        REFERENCES pedido (id_pedido)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    CONSTRAINT fk_pagamento_metodo_pagamento
        FOREIGN KEY (id_metodo_pagamento)
        REFERENCES metodo_pagamento (id_metodo_pagamento)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    CONSTRAINT fk_pagamento_status_pagamento
        FOREIGN KEY (id_status_pagamento)
        REFERENCES status_pagamento (id_status_pagamento)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    CONSTRAINT uq_pagamento_pedido_tentativa UNIQUE (id_pedido, tentativa),
    CONSTRAINT chk_pagamento_tentativa_positiva CHECK (tentativa > 0),
    CONSTRAINT chk_pagamento_valor_positivo CHECK (valor > 0)
);

CREATE TABLE tipo_movimentacao_estoque (
    id_tipo_movimentacao_estoque BIGINT GENERATED ALWAYS AS IDENTITY,
    codigo TEXT NOT NULL,
    nome TEXT NOT NULL,
    sinal SMALLINT NOT NULL,
    exige_pedido BOOLEAN NOT NULL DEFAULT FALSE,
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    ordem INTEGER NOT NULL DEFAULT 0,

    CONSTRAINT pk_tipo_movimentacao_estoque PRIMARY KEY (id_tipo_movimentacao_estoque),
    CONSTRAINT uq_tipo_movimentacao_estoque_codigo UNIQUE (codigo),
    CONSTRAINT uq_tipo_movimentacao_estoque_nome UNIQUE (nome),
    CONSTRAINT chk_tipo_movimentacao_estoque_codigo_nao_vazio CHECK (length(trim(codigo)) > 0),
    CONSTRAINT chk_tipo_movimentacao_estoque_nome_nao_vazio CHECK (length(trim(nome)) > 0),
    CONSTRAINT chk_tipo_movimentacao_estoque_sinal CHECK (sinal IN (-1, 1)),
    CONSTRAINT chk_tipo_movimentacao_estoque_ordem_nao_negativa CHECK (ordem >= 0)
);

INSERT INTO tipo_movimentacao_estoque (codigo, nome, sinal, exige_pedido, ordem)
VALUES
    ('entrada', 'Entrada', 1, FALSE, 1),
    ('saida', 'Saida', -1, FALSE, 2),
    ('ajuste_positivo', 'Ajuste positivo', 1, FALSE, 3),
    ('ajuste_negativo', 'Ajuste negativo', -1, FALSE, 4),
    ('venda', 'Venda', -1, TRUE, 5),
    ('cancelamento_venda', 'Cancelamento de venda', 1, TRUE, 6),
    ('transferencia_entrada', 'Transferencia de entrada', 1, FALSE, 7),
    ('transferencia_saida', 'Transferencia de saida', -1, FALSE, 8);

CREATE TABLE movimentacao_estoque (
    id_movimentacao_estoque BIGINT GENERATED ALWAYS AS IDENTITY,
    id_loja BIGINT NOT NULL,
    id_variacao BIGINT NOT NULL,
    id_pedido BIGINT,
    id_usuario_responsavel BIGINT,
    id_tipo_movimentacao_estoque BIGINT NOT NULL,
    quantidade INTEGER NOT NULL,
    quantidade_anterior INTEGER NOT NULL,
    quantidade_posterior INTEGER NOT NULL,
    motivo TEXT,
    criada_em TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT pk_movimentacao_estoque PRIMARY KEY (id_movimentacao_estoque),
    CONSTRAINT fk_movimentacao_estoque_loja
        FOREIGN KEY (id_loja)
        REFERENCES loja (id_loja)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    CONSTRAINT fk_movimentacao_estoque_variacao_produto
        FOREIGN KEY (id_variacao)
        REFERENCES variacao_produto (id_variacao)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    CONSTRAINT fk_movimentacao_estoque_pedido
        FOREIGN KEY (id_pedido)
        REFERENCES pedido (id_pedido)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    CONSTRAINT fk_movimentacao_estoque_usuario_responsavel
        FOREIGN KEY (id_usuario_responsavel)
        REFERENCES usuario (id_usuario)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    CONSTRAINT fk_movimentacao_estoque_tipo_movimentacao
        FOREIGN KEY (id_tipo_movimentacao_estoque)
        REFERENCES tipo_movimentacao_estoque (id_tipo_movimentacao_estoque)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    CONSTRAINT chk_movimentacao_estoque_quantidade_positiva CHECK (quantidade > 0),
    CONSTRAINT chk_movimentacao_estoque_saldos_nao_negativos CHECK (
        quantidade_anterior >= 0
        AND quantidade_posterior >= 0
    )
);

CREATE OR REPLACE FUNCTION validar_movimentacao_estoque()
RETURNS TRIGGER AS $$
DECLARE
    v_sinal SMALLINT;
    v_exige_pedido BOOLEAN;
BEGIN
    SELECT sinal, exige_pedido
    INTO v_sinal, v_exige_pedido
    FROM tipo_movimentacao_estoque
    WHERE id_tipo_movimentacao_estoque = NEW.id_tipo_movimentacao_estoque;

    IF v_sinal = 1
       AND NEW.quantidade_posterior <> NEW.quantidade_anterior + NEW.quantidade THEN
        RAISE EXCEPTION 'Saldo posterior invalido para movimentacao de entrada.';
    END IF;

    IF v_sinal = -1
       AND NEW.quantidade_posterior <> NEW.quantidade_anterior - NEW.quantidade THEN
        RAISE EXCEPTION 'Saldo posterior invalido para movimentacao de saida.';
    END IF;

    IF v_exige_pedido AND NEW.id_pedido IS NULL THEN
        RAISE EXCEPTION 'Este tipo de movimentacao exige pedido vinculado.';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_validar_movimentacao_estoque
BEFORE INSERT OR UPDATE ON movimentacao_estoque
FOR EACH ROW
EXECUTE FUNCTION validar_movimentacao_estoque();

CREATE INDEX idx_usuario_id_tipo_usuario ON usuario (id_tipo_usuario);
CREATE INDEX idx_usuario_id_loja ON usuario (id_loja);
CREATE INDEX idx_variacao_produto_id_produto ON variacao_produto (id_produto);
CREATE INDEX idx_estoque_id_variacao ON estoque (id_variacao);
CREATE INDEX idx_pedido_id_loja ON pedido (id_loja);
CREATE INDEX idx_pedido_id_cliente ON pedido (id_cliente);
CREATE INDEX idx_pedido_id_usuario_responsavel ON pedido (id_usuario_responsavel);
CREATE INDEX idx_pedido_id_status_pedido ON pedido (id_status_pedido);
CREATE INDEX idx_item_pedido_id_variacao ON item_pedido (id_variacao);
CREATE INDEX idx_pagamento_id_pedido ON pagamento (id_pedido);
CREATE INDEX idx_pagamento_id_metodo_pagamento ON pagamento (id_metodo_pagamento);
CREATE INDEX idx_pagamento_id_status_pagamento ON pagamento (id_status_pagamento);
CREATE INDEX idx_movimentacao_estoque_id_loja ON movimentacao_estoque (id_loja);
CREATE INDEX idx_movimentacao_estoque_id_variacao ON movimentacao_estoque (id_variacao);
CREATE INDEX idx_movimentacao_estoque_id_pedido ON movimentacao_estoque (id_pedido);
CREATE INDEX idx_movimentacao_estoque_id_usuario_responsavel ON movimentacao_estoque (id_usuario_responsavel);
CREATE INDEX idx_movimentacao_estoque_id_tipo_movimentacao ON movimentacao_estoque (id_tipo_movimentacao_estoque);
CREATE INDEX idx_movimentacao_estoque_criada_em ON movimentacao_estoque (criada_em);

COMMIT;
