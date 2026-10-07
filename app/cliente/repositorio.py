"""Consultas SQL da area do cliente."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.cliente.erros import (
    CadastroClienteNaoEncontrado,
    ChamadoClienteFinalizado,
    ChamadoClienteNaoEncontrado,
    EstoqueInsuficiente,
    LojaNaoEncontrada,
    PedidoClienteNaoEncontrado,
    ReferenciaChamadoInvalida,
    ReferenciaCheckoutInvalida,
    VariacaoIndisponivel,
)
from app.core.repositorio import buscar_todos, buscar_um, executar_sql, serializar_linha

CENTAVOS = Decimal("0.01")
STATUS_FINAIS_CHAMADO = ("resolvido", "encerrado", "cancelado")


def _dinheiro(valor: Decimal) -> Decimal:
    return valor.quantize(CENTAVOS)


def id_cliente_ativo(conexao, id_auth: UUID) -> UUID:
    linha = buscar_um(
        conexao,
        """
        SELECT u.id_usuario
        FROM usuario u
        JOIN tipo_usuario t ON t.id_tipo_usuario = u.id_tipo_usuario
        WHERE u.auth_user_id = %s
          AND u.ativo IS TRUE
          AND t.ativo IS TRUE
          AND t.codigo = 'cliente'
        """,
        (id_auth,),
    )
    if not linha:
        raise CadastroClienteNaoEncontrado
    return linha["id_usuario"]


def listar_lojas(conexao) -> list[dict[str, object]]:
    linhas = buscar_todos(
        conexao,
        """
        SELECT id_loja, nome, cidade, uf, endereco
        FROM loja
        WHERE ativa IS TRUE
        ORDER BY nome
        """,
    )
    return [serializar_linha(linha) for linha in linhas]


def perfil_cliente(conexao: Connection, id_cliente: UUID) -> dict[str, object]:
    linha = conexao.execute(
        text(
            """
            WITH resumo_pedidos AS (
                SELECT
                    count(*)::int AS total_pedidos,
                    COALESCE(sum(valor_total), 0)::numeric(12,2) AS valor_total_pedidos
                FROM pedido
                WHERE id_cliente = CAST(:cliente AS uuid)
            ),
            resumo_chamados AS (
                SELECT count(*)::int AS total_chamados
                FROM atendimento
                WHERE id_cliente = CAST(:cliente AS uuid)
            ),
            loja_preferida AS (
                SELECT l.id_loja, l.nome
                FROM pedido p
                JOIN loja l ON l.id_loja = p.id_loja
                WHERE p.id_cliente = CAST(:cliente AS uuid)
                ORDER BY p.criado_em DESC, p.id_pedido DESC
                LIMIT 1
            )
            SELECT
                u.id_usuario AS id_cliente,
                u.nome,
                u.email,
                u.telefone,
                u.documento,
                u.criado_em AS cliente_desde,
                rp.total_pedidos,
                rp.valor_total_pedidos,
                rc.total_chamados,
                lp.id_loja AS id_loja_preferida,
                lp.nome AS loja_preferida
            FROM usuario u
            CROSS JOIN resumo_pedidos rp
            CROSS JOIN resumo_chamados rc
            LEFT JOIN loja_preferida lp ON TRUE
            WHERE u.id_usuario = CAST(:cliente AS uuid)
            """
        ),
        {"cliente": str(id_cliente)},
    ).mappings().first()
    if not linha:
        raise CadastroClienteNaoEncontrado
    return dict(linha)


def _obter_id_por_codigo(conexao, tabela: str, coluna_id: str, codigo: str) -> object:
    linha = buscar_um(
        conexao,
        f"SELECT {coluna_id} FROM {tabela} WHERE codigo = %s AND ativo IS TRUE",
        (codigo,),
    )
    if not linha:
        raise ReferenciaCheckoutInvalida
    return linha[coluna_id]


def _garantir_loja_ativa(conexao, id_loja: UUID) -> None:
    linha = buscar_um(
        conexao,
        "SELECT id_loja FROM loja WHERE id_loja = %s AND ativa IS TRUE",
        (id_loja,),
    )
    if not linha:
        raise LojaNaoEncontrada


def _obter_variacao(conexao, id_variacao: UUID) -> dict[str, object]:
    linha = buscar_um(
        conexao,
        """
        SELECT
            v.id_variacao,
            v.sku,
            v.cor,
            v.tamanho,
            v.preco_venda,
            p.nome AS produto
        FROM variacao_produto v
        JOIN produto p ON p.id_produto = v.id_produto
        WHERE v.id_variacao = %s
          AND p.ativo IS TRUE
        """,
        (id_variacao,),
    )
    if not linha:
        raise VariacaoIndisponivel
    return linha


def _obter_estoque_para_atualizar(conexao, id_loja: UUID, id_variacao: UUID) -> dict[str, object]:
    linha = buscar_um(
        conexao,
        """
        SELECT id_estoque, quantidade
        FROM estoque
        WHERE id_loja = %s
          AND id_variacao = %s
        FOR UPDATE
        """,
        (id_loja, id_variacao),
    )
    return linha or {"quantidade": 0}


def _pagamento_do_pedido(conexao, id_pedido: UUID) -> dict[str, object] | None:
    linha = buscar_um(
        conexao,
        """
        SELECT
            g.id_pagamento,
            m.codigo AS metodo_codigo,
            m.nome AS metodo,
            s.codigo AS status_codigo,
            s.nome AS status,
            g.valor,
            g.processado_em
        FROM pagamento g
        JOIN metodo_pagamento m ON m.id_metodo_pagamento = g.id_metodo_pagamento
        JOIN status_pagamento s ON s.id_status_pagamento = g.id_status_pagamento
        WHERE g.id_pedido = %s
        ORDER BY g.tentativa
        LIMIT 1
        """,
        (id_pedido,),
    )
    return serializar_linha(linha) if linha else None


def _itens_do_pedido(conexao, id_pedido: UUID) -> list[dict[str, object]]:
    linhas = buscar_todos(
        conexao,
        """
        SELECT
            i.id_item_pedido,
            i.id_variacao,
            v.sku,
            p.nome AS produto,
            v.cor,
            v.tamanho,
            i.quantidade,
            i.preco_unitario,
            i.valor_total
        FROM item_pedido i
        JOIN variacao_produto v ON v.id_variacao = i.id_variacao
        JOIN produto p ON p.id_produto = v.id_produto
        WHERE i.id_pedido = %s
        ORDER BY p.nome, v.cor, v.tamanho
        """,
        (id_pedido,),
    )
    return [serializar_linha(linha) for linha in linhas]


def _pedido_base(conexao, id_cliente: UUID, id_pedido: UUID) -> dict[str, object]:
    linha = buscar_um(
        conexao,
        """
        SELECT
            p.id_pedido,
            p.numero_pedido,
            p.id_loja,
            l.nome AS loja,
            s.codigo AS status_codigo,
            s.nome AS status,
            p.valor_total,
            p.criado_em
        FROM pedido p
        JOIN loja l ON l.id_loja = p.id_loja
        JOIN status_pedido s ON s.id_status_pedido = p.id_status_pedido
        WHERE p.id_pedido = %s
          AND p.id_cliente = %s
        """,
        (id_pedido, id_cliente),
    )
    if not linha:
        raise PedidoClienteNaoEncontrado
    return linha


def obter_pedido_cliente(conexao, id_cliente: UUID, id_pedido: UUID) -> dict[str, object]:
    pedido = serializar_linha(_pedido_base(conexao, id_cliente, id_pedido))
    pedido["itens"] = _itens_do_pedido(conexao, id_pedido)
    pedido["pagamento"] = _pagamento_do_pedido(conexao, id_pedido)
    return pedido


def listar_pedidos_cliente(
    conexao,
    id_cliente: UUID,
    *,
    limit: int,
    offset: int,
) -> list[dict[str, object]]:
    linhas = buscar_todos(
        conexao,
        """
        SELECT p.id_pedido
        FROM pedido p
        WHERE p.id_cliente = %s
        ORDER BY p.criado_em DESC
        LIMIT %s OFFSET %s
        """,
        (id_cliente, limit, offset),
    )
    return [obter_pedido_cliente(conexao, id_cliente, linha["id_pedido"]) for linha in linhas]


# ---------------------------------------------------------------- chamados do cliente


def _mapas(conexao: Connection, sql: str, parametros: dict[str, object]) -> list[dict[str, object]]:
    return [dict(linha) for linha in conexao.execute(text(sql), parametros).mappings()]


def opcoes_chamado(conexao: Connection) -> dict[str, object]:
    categorias = _mapas(
        conexao,
        """
        SELECT codigo, nome
        FROM categoria_atendimento
        WHERE ativo
        ORDER BY ordem, nome
        """,
        {},
    )
    return {"categorias": categorias}


def _obter_id_opcao_atendimento(
    conexao: Connection, tabela: str, coluna_id: str, codigo: str
) -> object:
    linha = conexao.execute(
        text(
            f"""
            SELECT {coluna_id}
            FROM {tabela}
            WHERE codigo = :codigo
              AND ativo
            """  # nosec B608 - tabela e coluna sao constantes escolhidas pelo codigo.
        ),
        {"codigo": codigo},
    ).mappings().first()
    if not linha:
        raise ReferenciaChamadoInvalida
    return linha[coluna_id]


def _prioridade_padrao(categoria: str) -> str:
    if categoria in {"produto", "troca_devolucao"}:
        return "alta"
    if categoria in {"pedido", "entrega", "pagamento"}:
        return "media"
    return "baixa"


def _contexto_pedido_item(
    conexao: Connection,
    id_cliente: UUID,
    *,
    id_loja: UUID | None,
    id_pedido: UUID | None,
    id_item_pedido: UUID | None,
) -> dict[str, object]:
    if id_item_pedido is not None:
        linhas = _mapas(
            conexao,
            """
            SELECT p.id_pedido, p.id_loja, p.numero_pedido, ip.id_item_pedido
            FROM item_pedido ip
            JOIN pedido p ON p.id_pedido = ip.id_pedido
            WHERE ip.id_item_pedido = CAST(:item AS uuid)
              AND p.id_cliente = CAST(:cliente AS uuid)
              AND (CAST(:pedido AS uuid) IS NULL OR p.id_pedido = CAST(:pedido AS uuid))
            """,
            {
                "cliente": str(id_cliente),
                "pedido": str(id_pedido) if id_pedido else None,
                "item": str(id_item_pedido),
            },
        )
        if not linhas:
            raise PedidoClienteNaoEncontrado
        return linhas[0]

    if id_pedido is not None:
        linhas = _mapas(
            conexao,
            """
            SELECT p.id_pedido, p.id_loja, p.numero_pedido, NULL::uuid AS id_item_pedido
            FROM pedido p
            WHERE p.id_pedido = CAST(:pedido AS uuid)
              AND p.id_cliente = CAST(:cliente AS uuid)
            """,
            {"cliente": str(id_cliente), "pedido": str(id_pedido)},
        )
        if not linhas:
            raise PedidoClienteNaoEncontrado
        return linhas[0]

    if id_loja is not None:
        _garantir_loja_ativa(conexao, id_loja)

    return {"id_pedido": None, "id_loja": id_loja, "numero_pedido": None, "id_item_pedido": None}


def _linha_chamado(linha: dict[str, object]) -> dict[str, object]:
    return {
        "id_atendimento": linha["id_atendimento"],
        "protocolo": linha["protocolo"],
        "assunto": linha["assunto"],
        "categoria": {"codigo": linha["categoria_codigo"], "nome": linha["categoria_nome"]},
        "status": {"codigo": linha["status_codigo"], "nome": linha["status_nome"]},
        "id_pedido": linha["id_pedido"],
        "numero_pedido": linha["numero_pedido"],
        "id_loja": linha["id_loja"],
        "loja_nome": linha["loja_nome"],
        "aberto_em": linha["aberto_em"],
        "atualizado_em": linha["atualizado_em"],
        "ultima_mensagem_em": linha["ultima_mensagem_em"],
    }


COLUNAS_CHAMADO_CLIENTE = """
    a.id_atendimento,
    a.protocolo,
    COALESCE(a.assunto, ct.nome) AS assunto,
    ct.codigo AS categoria_codigo,
    ct.nome AS categoria_nome,
    st.codigo AS status_codigo,
    st.nome AS status_nome,
    a.id_pedido,
    p.numero_pedido,
    a.id_loja,
    lj.nome AS loja_nome,
    a.aberto_em,
    a.atualizado_em,
    max(m.enviada_em) AS ultima_mensagem_em
"""


DE_ONDE_CHAMADO_CLIENTE = """
    FROM atendimento a
    JOIN status_atendimento st ON st.id_status_atendimento = a.id_status_atendimento
    JOIN categoria_atendimento ct ON ct.id_categoria_atendimento = a.id_categoria_atendimento
    LEFT JOIN pedido p ON p.id_pedido = a.id_pedido
    LEFT JOIN loja lj ON lj.id_loja = a.id_loja
    LEFT JOIN mensagem m ON m.id_atendimento = a.id_atendimento
"""


AGRUPAR_CHAMADO_CLIENTE = """
    GROUP BY a.id_atendimento, a.protocolo, a.assunto, ct.nome, ct.codigo, st.codigo, st.nome,
             a.id_pedido, p.numero_pedido, a.id_loja, lj.nome, a.aberto_em, a.atualizado_em
"""


def listar_chamados_cliente(
    conexao: Connection,
    id_cliente: UUID,
    *,
    limit: int,
    offset: int,
) -> list[dict[str, object]]:
    linhas = _mapas(
        conexao,
        f"""
        SELECT {COLUNAS_CHAMADO_CLIENTE}
        {DE_ONDE_CHAMADO_CLIENTE}
        WHERE a.id_cliente = CAST(:cliente AS uuid)
        {AGRUPAR_CHAMADO_CLIENTE}
        ORDER BY COALESCE(max(m.enviada_em), a.aberto_em) DESC, a.id_atendimento
        LIMIT :limite OFFSET :deslocamento
        """,  # nosec B608 - fragmentos SQL sao constantes deste modulo.
        {"cliente": str(id_cliente), "limite": limit, "deslocamento": offset},
    )
    return [_linha_chamado(linha) for linha in linhas]


def _buscar_chamado_cliente(
    conexao: Connection, id_cliente: UUID, id_atendimento: UUID
) -> dict[str, object] | None:
    linhas = _mapas(
        conexao,
        f"""
        SELECT {COLUNAS_CHAMADO_CLIENTE}
        {DE_ONDE_CHAMADO_CLIENTE}
        WHERE a.id_cliente = CAST(:cliente AS uuid)
          AND a.id_atendimento = CAST(:id AS uuid)
        {AGRUPAR_CHAMADO_CLIENTE}
        """,  # nosec B608 - fragmentos SQL sao constantes deste modulo.
        {"cliente": str(id_cliente), "id": str(id_atendimento)},
    )
    return _linha_chamado(linhas[0]) if linhas else None


def _pecas_chamado(conexao: Connection, id_atendimento: UUID) -> list[dict[str, object]]:
    return _mapas(
        conexao,
        """
        SELECT
            ip.id_item_pedido,
            ip.id_variacao,
            v.sku,
            pd.nome AS produto,
            v.cor,
            v.tamanho,
            ip.quantidade
        FROM atendimento_item ai
        JOIN item_pedido ip ON ip.id_item_pedido = ai.id_item_pedido
        JOIN variacao_produto v ON v.id_variacao = ip.id_variacao
        JOIN produto pd ON pd.id_produto = v.id_produto
        WHERE ai.id_atendimento = CAST(:id AS uuid)
        ORDER BY pd.nome, v.sku
        """,
        {"id": str(id_atendimento)},
    )


def _anexos_chamado(conexao: Connection, id_atendimento: UUID) -> list[dict[str, object]]:
    return _mapas(
        conexao,
        """
        SELECT id_anexo, nome, caminho, criado_em
        FROM chamado_anexo
        WHERE id_atendimento = CAST(:id AS uuid)
        ORDER BY criado_em, id_anexo
        """,
        {"id": str(id_atendimento)},
    )


def obter_chamado_cliente(
    conexao: Connection, id_cliente: UUID, id_atendimento: UUID
) -> dict[str, object]:
    chamado = _buscar_chamado_cliente(conexao, id_cliente, id_atendimento)
    if chamado is None:
        raise ChamadoClienteNaoEncontrado
    chamado["pecas"] = _pecas_chamado(conexao, id_atendimento)
    chamado["anexos"] = _anexos_chamado(conexao, id_atendimento)
    return chamado


def listar_mensagens_chamado_cliente(
    conexao: Connection, id_cliente: UUID, id_atendimento: UUID
) -> list[dict[str, object]]:
    if _buscar_chamado_cliente(conexao, id_cliente, id_atendimento) is None:
        raise ChamadoClienteNaoEncontrado
    linhas = _mapas(
        conexao,
        """
        SELECT m.id_mensagem, m.texto, m.enviada_em, u.nome, (t.codigo <> 'cliente') AS da_equipe
        FROM mensagem m
        JOIN usuario u ON u.id_usuario = m.id_usuario_remetente
        JOIN tipo_usuario t ON t.id_tipo_usuario = u.id_tipo_usuario
        WHERE m.id_atendimento = CAST(:id AS uuid)
        ORDER BY m.enviada_em, m.id_mensagem
        LIMIT 500
        """,
        {"id": str(id_atendimento)},
    )
    return [
        {
            "id_mensagem": linha["id_mensagem"],
            "autor": "atendente" if linha["da_equipe"] else "cliente",
            "nome": linha["nome"],
            "texto": linha["texto"],
            "enviada_em": linha["enviada_em"],
        }
        for linha in linhas
    ]


def criar_chamado_cliente(
    conexao: Connection,
    id_cliente: UUID,
    dados: dict[str, object],
) -> dict[str, object]:
    try:
        categoria = str(dados["categoria"])
        contexto = _contexto_pedido_item(
            conexao,
            id_cliente,
            id_loja=dados.get("id_loja"),
            id_pedido=dados.get("id_pedido"),
            id_item_pedido=dados.get("id_item_pedido"),
        )
        id_status = _obter_id_opcao_atendimento(
            conexao, "status_atendimento", "id_status_atendimento", "aberto"
        )
        id_canal = _obter_id_opcao_atendimento(
            conexao, "canal_atendimento", "id_canal_atendimento", "site"
        )
        id_categoria = _obter_id_opcao_atendimento(
            conexao, "categoria_atendimento", "id_categoria_atendimento", categoria
        )
        id_prioridade = _obter_id_opcao_atendimento(
            conexao,
            "prioridade_atendimento",
            "id_prioridade_atendimento",
            _prioridade_padrao(categoria),
        )
        id_atendimento = conexao.execute(
            text(
                """
                INSERT INTO atendimento (
                    id_cliente,
                    id_pedido,
                    id_loja,
                    id_canal_atendimento,
                    id_categoria_atendimento,
                    id_prioridade_atendimento,
                    id_status_atendimento,
                    assunto
                )
                VALUES (
                    CAST(:cliente AS uuid),
                    CAST(:pedido AS uuid),
                    CAST(:loja AS uuid),
                    CAST(:canal AS uuid),
                    CAST(:categoria AS uuid),
                    CAST(:prioridade AS uuid),
                    CAST(:status AS uuid),
                    :assunto
                )
                RETURNING id_atendimento
                """
            ),
            {
                "cliente": str(id_cliente),
                "pedido": str(contexto["id_pedido"]) if contexto["id_pedido"] else None,
                "loja": str(contexto["id_loja"]) if contexto["id_loja"] else None,
                "canal": str(id_canal),
                "categoria": str(id_categoria),
                "prioridade": str(id_prioridade),
                "status": str(id_status),
                "assunto": dados["assunto"],
            },
        ).scalar_one()
        if contexto["id_item_pedido"]:
            conexao.execute(
                text(
                    """
                    INSERT INTO atendimento_item (id_atendimento, id_item_pedido)
                    VALUES (CAST(:atendimento AS uuid), CAST(:item AS uuid))
                    ON CONFLICT DO NOTHING
                    """
                ),
                {"atendimento": str(id_atendimento), "item": str(contexto["id_item_pedido"])},
            )
        conexao.execute(
            text(
                """
                INSERT INTO mensagem (id_atendimento, id_usuario_remetente, texto)
                VALUES (CAST(:atendimento AS uuid), CAST(:cliente AS uuid), :texto)
                """
            ),
            {
                "atendimento": str(id_atendimento),
                "cliente": str(id_cliente),
                "texto": dados["descricao"],
            },
        )
        conexao.commit()
    except Exception:
        conexao.rollback()
        raise

    return obter_chamado_cliente(conexao, id_cliente, id_atendimento)


def enviar_mensagem_chamado_cliente(
    conexao: Connection,
    id_cliente: UUID,
    id_atendimento: UUID,
    texto_mensagem: str,
) -> dict[str, object]:
    try:
        linha = conexao.execute(
            text(
                """
                SELECT st.codigo AS status_codigo
                FROM atendimento a
                JOIN status_atendimento st ON st.id_status_atendimento = a.id_status_atendimento
                WHERE a.id_atendimento = CAST(:id AS uuid)
                  AND a.id_cliente = CAST(:cliente AS uuid)
                FOR UPDATE
                """
            ),
            {"id": str(id_atendimento), "cliente": str(id_cliente)},
        ).mappings().first()
        if not linha:
            raise ChamadoClienteNaoEncontrado
        if linha["status_codigo"] in STATUS_FINAIS_CHAMADO:
            raise ChamadoClienteFinalizado
        id_mensagem = conexao.execute(
            text(
                """
                INSERT INTO mensagem (id_atendimento, id_usuario_remetente, texto)
                VALUES (CAST(:atendimento AS uuid), CAST(:cliente AS uuid), :texto)
                RETURNING id_mensagem
                """
            ),
            {
                "atendimento": str(id_atendimento),
                "cliente": str(id_cliente),
                "texto": texto_mensagem,
            },
        ).scalar_one()
        conexao.execute(
            text(
                """
                UPDATE atendimento
                SET atualizado_em = now(),
                    id_status_atendimento = CASE
                        WHEN id_status_atendimento = (
                            SELECT id_status_atendimento
                            FROM status_atendimento
                            WHERE codigo = 'aguardando_cliente'
                        ) THEN (
                            SELECT id_status_atendimento
                            FROM status_atendimento
                            WHERE codigo = 'em_andamento'
                        )
                        ELSE id_status_atendimento
                    END
                WHERE id_atendimento = CAST(:id AS uuid)
                """
            ),
            {"id": str(id_atendimento)},
        )
        conexao.commit()
    except Exception:
        conexao.rollback()
        raise

    mensagens = listar_mensagens_chamado_cliente(conexao, id_cliente, id_atendimento)
    return next(m for m in mensagens if m["id_mensagem"] == id_mensagem)


def _pedido_por_chave(conexao, id_cliente: UUID, chave_idempotencia: str | None):
    if not chave_idempotencia:
        return None
    linha = buscar_um(
        conexao,
        """
        SELECT p.id_pedido
        FROM pedido p
        JOIN pagamento g ON g.id_pedido = p.id_pedido
        WHERE p.id_cliente = %s
          AND g.transacao_externa_id = %s
        ORDER BY p.criado_em DESC
        LIMIT 1
        """,
        (id_cliente, f"checkout-{chave_idempotencia}"),
    )
    return linha["id_pedido"] if linha else None


def criar_checkout(
    conexao,
    id_cliente: UUID,
    dados: dict[str, object],
    *,
    chave_idempotencia: str | None = None,
) -> dict[str, object]:
    existente = _pedido_por_chave(conexao, id_cliente, chave_idempotencia)
    if existente:
        return obter_pedido_cliente(conexao, id_cliente, existente)

    try:
        id_loja = dados["id_loja"]
        _garantir_loja_ativa(conexao, id_loja)
        id_status_pedido = _obter_id_por_codigo(conexao, "status_pedido", "id_status_pedido", "pago")
        id_metodo_pagamento = _obter_id_por_codigo(
            conexao,
            "metodo_pagamento",
            "id_metodo_pagamento",
            str(dados["metodo_pagamento"]),
        )
        id_status_pagamento = _obter_id_por_codigo(
            conexao,
            "status_pagamento",
            "id_status_pagamento",
            "aprovado",
        )
        id_tipo_venda = _obter_id_por_codigo(
            conexao,
            "tipo_movimentacao_estoque",
            "id_tipo_movimentacao_estoque",
            "venda",
        )
        frete = _dinheiro(dados["frete"])
        numero = f"PD-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:8].upper()}"
        partes_observacao = [
            "Checkout pelo portal.",
            f"Entrega: {dados['entrega']}.",
            f"Frete: R$ {frete}.",
        ]
        endereco = dados.get("endereco_entrega")
        if isinstance(endereco, dict):
            partes_endereco = [
                str(endereco.get("rua") or "").strip(),
                str(endereco.get("numero") or "").strip(),
                str(endereco.get("complemento") or "").strip(),
                str(endereco.get("cep") or "").strip(),
                str(endereco.get("uf") or "").strip().upper(),
            ]
            texto_endereco = ", ".join(parte for parte in partes_endereco if parte)
            if texto_endereco:
                partes_observacao.append(f"Endereco de entrega: {texto_endereco}.")
        observacao = " ".join(partes_observacao)

        pedido = executar_sql(
            conexao,
            """
            INSERT INTO pedido (
                numero_pedido,
                id_loja,
                id_cliente,
                id_status_pedido,
                valor_total,
                observacao
            )
            VALUES (%s, %s, %s, %s, 0, %s)
            RETURNING id_pedido
            """,
            (numero, id_loja, id_cliente, id_status_pedido, observacao),
        ).mappings().first()
        id_pedido = pedido["id_pedido"]

        subtotal = Decimal("0.00")
        for item in dados["itens"]:
            id_variacao = item["id_variacao"]
            quantidade = item["quantidade"]
            variacao = _obter_variacao(conexao, id_variacao)
            preco = _dinheiro(variacao["preco_venda"])
            estoque = _obter_estoque_para_atualizar(conexao, id_loja, id_variacao)
            quantidade_anterior = int(estoque["quantidade"])
            if quantidade_anterior < quantidade:
                raise EstoqueInsuficiente(str(variacao["sku"]), quantidade_anterior)
            quantidade_posterior = quantidade_anterior - quantidade

            executar_sql(
                conexao,
                """
                INSERT INTO item_pedido (id_pedido, id_variacao, quantidade, preco_unitario)
                VALUES (%s, %s, %s, %s)
                """,
                (id_pedido, id_variacao, quantidade, preco),
            )
            executar_sql(
                conexao,
                """
                UPDATE estoque
                SET quantidade = %s,
                    atualizado_em = now()
                WHERE id_loja = %s
                  AND id_variacao = %s
                """,
                (quantidade_posterior, id_loja, id_variacao),
            )
            executar_sql(
                conexao,
                """
                INSERT INTO movimentacao_estoque (
                    id_loja,
                    id_variacao,
                    id_pedido,
                    id_tipo_movimentacao_estoque,
                    quantidade,
                    quantidade_anterior,
                    quantidade_posterior,
                    motivo
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    id_loja,
                    id_variacao,
                    id_pedido,
                    id_tipo_venda,
                    quantidade,
                    quantidade_anterior,
                    quantidade_posterior,
                    f"Saida de estoque referente ao pedido {numero}.",
                ),
            )
            subtotal += preco * quantidade

        total = _dinheiro(subtotal + frete)
        executar_sql(
            conexao,
            "UPDATE pedido SET valor_total = %s, atualizado_em = now() WHERE id_pedido = %s",
            (total, id_pedido),
        )
        executar_sql(
            conexao,
            """
            INSERT INTO pagamento (
                id_pedido,
                tentativa,
                id_metodo_pagamento,
                id_status_pagamento,
                valor,
                transacao_externa_id,
                processado_em
            )
            VALUES (%s, 1, %s, %s, %s, %s, now())
            """,
            (
                id_pedido,
                id_metodo_pagamento,
                id_status_pagamento,
                total,
                f"checkout-{chave_idempotencia or numero}",
            ),
        )
        conexao.commit()
    except Exception:
        conexao.rollback()
        raise

    return obter_pedido_cliente(conexao, id_cliente, id_pedido)
