DO $$
DECLARE
    v_id_loja BIGINT;
    v_id_tipo_cliente BIGINT;
    v_id_tipo_gerente BIGINT;
    v_id_cliente BIGINT;
    v_id_usuario_responsavel BIGINT;
    v_id_produto BIGINT;
    v_id_variacao_p BIGINT;
    v_id_variacao_m BIGINT;
    v_id_status_pedido_pago BIGINT;
    v_id_metodo_pagamento_pix BIGINT;
    v_id_status_pagamento_aprovado BIGINT;
    v_id_tipo_movimentacao_venda BIGINT;
    v_id_pedido BIGINT;
    v_quantidade_anterior INTEGER;
    v_quantidade_posterior INTEGER;
    v_linhas_atualizadas INTEGER;
BEGIN
    IF EXISTS (SELECT 1 FROM pedido WHERE numero_pedido = 'PED-0001') THEN
        RAISE NOTICE 'Seed ja aplicado. Pedido PED-0001 encontrado.';
        RETURN;
    END IF;

    SELECT id_tipo_usuario
    INTO v_id_tipo_cliente
    FROM tipo_usuario
    WHERE codigo = 'cliente';

    SELECT id_tipo_usuario
    INTO v_id_tipo_gerente
    FROM tipo_usuario
    WHERE codigo = 'gerente_loja';

    SELECT id_status_pedido
    INTO v_id_status_pedido_pago
    FROM status_pedido
    WHERE codigo = 'pago';

    SELECT id_metodo_pagamento
    INTO v_id_metodo_pagamento_pix
    FROM metodo_pagamento
    WHERE codigo = 'pix';

    SELECT id_status_pagamento
    INTO v_id_status_pagamento_aprovado
    FROM status_pagamento
    WHERE codigo = 'aprovado';

    SELECT id_tipo_movimentacao_estoque
    INTO v_id_tipo_movimentacao_venda
    FROM tipo_movimentacao_estoque
    WHERE codigo = 'venda';

    INSERT INTO loja (codigo, nome, cnpj, email, telefone, endereco, cidade, uf)
    VALUES (
        'LOJA-CENTRO',
        'Casa Lorenzi Centro',
        '12345678000190',
        'centro@casalorenzi.example',
        '(11) 4002-8922',
        'Rua das Flores, 100',
        'Sao Paulo',
        'SP'
    )
    ON CONFLICT (codigo) DO UPDATE
        SET nome = EXCLUDED.nome,
            email = EXCLUDED.email,
            telefone = EXCLUDED.telefone,
            endereco = EXCLUDED.endereco,
            cidade = EXCLUDED.cidade,
            uf = EXCLUDED.uf,
            atualizada_em = now()
    RETURNING id_loja INTO v_id_loja;

    INSERT INTO usuario (id_tipo_usuario, nome, email, telefone, documento)
    VALUES (
        v_id_tipo_cliente,
        'Ana Souza',
        'ana.souza@example.com',
        '(11) 99999-0001',
        '12345678901'
    )
    ON CONFLICT (email) DO UPDATE
        SET id_tipo_usuario = EXCLUDED.id_tipo_usuario,
            nome = EXCLUDED.nome,
            telefone = EXCLUDED.telefone,
            documento = EXCLUDED.documento,
            atualizado_em = now()
    RETURNING id_usuario INTO v_id_cliente;

    INSERT INTO usuario (id_tipo_usuario, id_loja, nome, email, telefone)
    VALUES (
        v_id_tipo_gerente,
        v_id_loja,
        'Vitor Almeida',
        'vitor.almeida@casalorenzi.example',
        '(11) 99999-0002'
    )
    ON CONFLICT (email) DO UPDATE
        SET id_tipo_usuario = EXCLUDED.id_tipo_usuario,
            id_loja = EXCLUDED.id_loja,
            nome = EXCLUDED.nome,
            telefone = EXCLUDED.telefone,
            atualizado_em = now()
    RETURNING id_usuario INTO v_id_usuario_responsavel;

    INSERT INTO produto (nome, marca, categoria, descricao, preco_base)
    VALUES (
        'Camisa Linho Essencial',
        'Casa Lorenzi',
        'Camisas',
        'Camisa de linho com modelagem regular.',
        149.90
    )
    ON CONFLICT ON CONSTRAINT uq_produto_nome_marca DO UPDATE
        SET categoria = EXCLUDED.categoria,
            descricao = EXCLUDED.descricao,
            preco_base = EXCLUDED.preco_base,
            atualizado_em = now()
    RETURNING id_produto INTO v_id_produto;

    INSERT INTO variacao_produto (id_produto, sku, cor, tamanho, preco_venda)
    VALUES (v_id_produto, 'CL-CAM-LIN-BR-P', 'Branco', 'P', 149.90)
    ON CONFLICT (sku) DO UPDATE
        SET id_produto = EXCLUDED.id_produto,
            cor = EXCLUDED.cor,
            tamanho = EXCLUDED.tamanho,
            preco_venda = EXCLUDED.preco_venda,
            atualizada_em = now()
    RETURNING id_variacao INTO v_id_variacao_p;

    INSERT INTO variacao_produto (id_produto, sku, cor, tamanho, preco_venda)
    VALUES (v_id_produto, 'CL-CAM-LIN-BR-M', 'Branco', 'M', 149.90)
    ON CONFLICT (sku) DO UPDATE
        SET id_produto = EXCLUDED.id_produto,
            cor = EXCLUDED.cor,
            tamanho = EXCLUDED.tamanho,
            preco_venda = EXCLUDED.preco_venda,
            atualizada_em = now()
    RETURNING id_variacao INTO v_id_variacao_m;

    INSERT INTO estoque (id_loja, id_variacao, quantidade, estoque_minimo)
    VALUES (v_id_loja, v_id_variacao_p, 15, 3)
    ON CONFLICT (id_loja, id_variacao) DO UPDATE
        SET quantidade = EXCLUDED.quantidade,
            estoque_minimo = EXCLUDED.estoque_minimo,
            atualizado_em = now();

    INSERT INTO estoque (id_loja, id_variacao, quantidade, estoque_minimo)
    VALUES (v_id_loja, v_id_variacao_m, 8, 2)
    ON CONFLICT (id_loja, id_variacao) DO UPDATE
        SET quantidade = EXCLUDED.quantidade,
            estoque_minimo = EXCLUDED.estoque_minimo,
            atualizado_em = now();

    INSERT INTO pedido (
        numero_pedido,
        id_loja,
        id_cliente,
        id_usuario_responsavel,
        id_status_pedido,
        valor_total,
        observacao
    )
    VALUES (
        'PED-0001',
        v_id_loja,
        v_id_cliente,
        v_id_usuario_responsavel,
        v_id_status_pedido_pago,
        299.80,
        'Pedido de teste para validar o fluxo inicial.'
    )
    RETURNING id_pedido INTO v_id_pedido;

    INSERT INTO item_pedido (id_pedido, id_variacao, quantidade, preco_unitario)
    VALUES (v_id_pedido, v_id_variacao_p, 2, 149.90);

    INSERT INTO pagamento (
        id_pedido,
        tentativa,
        id_metodo_pagamento,
        id_status_pagamento,
        valor,
        transacao_externa_id,
        processado_em
    )
    VALUES (
        v_id_pedido,
        1,
        v_id_metodo_pagamento_pix,
        v_id_status_pagamento_aprovado,
        299.80,
        'teste-pix-0001',
        now()
    );

    SELECT quantidade
    INTO v_quantidade_anterior
    FROM estoque
    WHERE id_loja = v_id_loja
      AND id_variacao = v_id_variacao_p
    FOR UPDATE;

    UPDATE estoque
    SET quantidade = quantidade - 2,
        atualizado_em = now()
    WHERE id_loja = v_id_loja
      AND id_variacao = v_id_variacao_p
      AND quantidade >= 2
    RETURNING quantidade INTO v_quantidade_posterior;

    GET DIAGNOSTICS v_linhas_atualizadas = ROW_COUNT;

    IF v_linhas_atualizadas <> 1 THEN
        RAISE EXCEPTION 'Estoque insuficiente para aplicar o pedido de teste PED-0001.';
    END IF;

    INSERT INTO movimentacao_estoque (
        id_loja,
        id_variacao,
        id_pedido,
        id_usuario_responsavel,
        id_tipo_movimentacao_estoque,
        quantidade,
        quantidade_anterior,
        quantidade_posterior,
        motivo
    )
    VALUES (
        v_id_loja,
        v_id_variacao_p,
        v_id_pedido,
        v_id_usuario_responsavel,
        v_id_tipo_movimentacao_venda,
        2,
        v_quantidade_anterior,
        v_quantidade_posterior,
        'Saida de estoque referente ao pedido PED-0001.'
    );
END $$;
