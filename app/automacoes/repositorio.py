"""Consultas das automacoes. A conexao ignora RLS: so devolvem o que o n8n precisa para avisar."""

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.cliente.repositorio import SALDO_E_CREDITOS_NO_ANO

# Cliente ativo que aceita mensagens, com o contato do canal preenchido.
CONTATOS = f"""
SELECT u.id_usuario, u.nome, u.email, u.telefone, {SALDO_E_CREDITOS_NO_ANO}
FROM usuario u
JOIN tipo_usuario t ON t.id_tipo_usuario = u.id_tipo_usuario AND t.codigo = 'cliente'
LEFT JOIN movimento_pontos m ON m.id_usuario = u.id_usuario
WHERE u.id_usuario = ANY(CAST(:ids AS uuid[]))
  AND u.ativo
  AND u.aceita_mensagens
  AND CASE CAST(:canal AS text)
          WHEN 'email' THEN COALESCE(u.email, '') <> ''
          ELSE COALESCE(u.telefone, '') <> ''
      END
GROUP BY u.id_usuario
ORDER BY u.nome
"""  # nosec B608


def contatos(conexao: Connection, ids: list[UUID], canal: str) -> list[dict[str, Any]]:
    if not ids:
        return []
    linhas = conexao.execute(
        text(CONTATOS), {"ids": [str(i) for i in ids], "canal": canal}
    ).mappings()
    return [dict(linha) for linha in linhas]


def avisados(conexao: Connection, ids: list[UUID], canal: str) -> set[tuple[UUID, Any]]:
    if not ids:
        return set()
    linhas = conexao.execute(
        text(
            """
            SELECT id_usuario, vence_em FROM aviso_pontos
            WHERE canal = :canal AND id_usuario = ANY(CAST(:ids AS uuid[]))
            """
        ),
        {"ids": [str(i) for i in ids], "canal": canal},
    ).all()
    return {(linha.id_usuario, linha.vence_em) for linha in linhas}


def gravar_avisos(conexao: Connection, canal: str, avisos: str) -> int:
    """`avisos` e um JSON (lista de {id_cliente, vence_em, pontos}). Repetido e ignorado; cliente
    inexistente tambem (o JOIN descarta), em vez de derrubar o lote inteiro."""
    gravados = conexao.execute(
        text(
            """
            INSERT INTO aviso_pontos (id_usuario, vence_em, pontos, canal)
            SELECT a.id_cliente, a.vence_em, a.pontos, :canal
            FROM jsonb_to_recordset(CAST(:avisos AS jsonb))
                 AS a(id_cliente uuid, vence_em timestamptz, pontos int)
            JOIN usuario u ON u.id_usuario = a.id_cliente
            ON CONFLICT (id_usuario, vence_em, canal) DO NOTHING
            """
        ),
        {"canal": canal, "avisos": avisos},
    ).rowcount
    conexao.commit()
    return gravados


def nomes_das_lojas(conexao: Connection) -> dict[UUID, str]:
    return dict(conexao.execute(text("SELECT id_loja, nome FROM loja")).all())


# ---------------------------------------------------------------- estoque (operador)


def lojas_ativas(conexao: Connection, *, so_fisicas: bool = False) -> list[dict[str, Any]]:
    """`so_fisicas`: so as lojas de rua e shopping, que tem horario de atendimento cadastrado (CD,
    e-commerce e app nao tem)."""
    linhas = conexao.execute(
        text(
            """
            SELECT id_loja, nome FROM loja
            WHERE ativa AND (NOT :so_fisicas OR horario_funcionamento IS NOT NULL)
            ORDER BY nome
            """
        ),
        {"so_fisicas": so_fisicas},
    ).mappings()
    return [dict(linha) for linha in linhas]


# Pecas no minimo ou abaixo dele (so onde a loja definiu um minimo), com ate 3 outras lojas que
# tem sobra da mesma peca (saldo acima do minimo delas), para pedir transferencia antes de comprar.
ABAIXO_DO_MINIMO = """
SELECT e.id_loja, v.sku, p.nome AS produto, v.cor, v.tamanho,
       e.quantidade AS saldo, e.estoque_minimo AS minimo,
       COALESCE(sobra.lojas, '[]'::json) AS lojas_com_sobra
FROM estoque e
JOIN loja l ON l.id_loja = e.id_loja AND l.ativa
JOIN variacao_produto v ON v.id_variacao = e.id_variacao AND v.ativa
JOIN produto p ON p.id_produto = v.id_produto AND p.ativo
LEFT JOIN LATERAL (
    SELECT json_agg(json_build_object('loja', x.nome, 'sobra', x.sobra)
                    ORDER BY x.sobra DESC, x.nome) AS lojas
    FROM (
        SELECT o.nome, e2.quantidade - e2.estoque_minimo AS sobra
        FROM estoque e2
        JOIN loja o ON o.id_loja = e2.id_loja AND o.ativa
        WHERE e2.id_variacao = e.id_variacao
          AND e2.id_loja <> e.id_loja
          AND e2.quantidade > e2.estoque_minimo
        ORDER BY sobra DESC, o.nome
        LIMIT 3
    ) x
) sobra ON TRUE
WHERE e.estoque_minimo > 0 AND e.quantidade <= e.estoque_minimo
ORDER BY l.nome, e.quantidade, p.nome, v.cor, v.tamanho
"""


def abaixo_do_minimo(conexao: Connection) -> list[dict[str, Any]]:
    return [dict(linha) for linha in conexao.execute(text(ABAIXO_DO_MINIMO)).mappings()]


# Transferencias paradas: solicitadas sem resposta ha mais de :horas, ou aceitas (em transito)
# sem confirmacao de recebimento ha mais de :dias.
TRANSFERENCIAS_PARADAS = """
SELECT t.id_transferencia_estoque AS id_transferencia, tipo.codigo AS tipo, st.codigo AS status,
       t.id_loja_origem, origem.nome AS origem, t.id_loja_destino, destino.nome AS destino,
       v.sku, p.nome AS produto, v.cor, v.tamanho, t.quantidade, t.solicitada_em, t.aceita_em
FROM transferencia_estoque t
JOIN tipo_transferencia_estoque tipo
    ON tipo.id_tipo_transferencia_estoque = t.id_tipo_transferencia_estoque
JOIN status_transferencia_estoque st
    ON st.id_status_transferencia_estoque = t.id_status_transferencia_estoque
LEFT JOIN loja origem ON origem.id_loja = t.id_loja_origem
JOIN loja destino ON destino.id_loja = t.id_loja_destino
JOIN variacao_produto v ON v.id_variacao = t.id_variacao
JOIN produto p ON p.id_produto = v.id_produto
WHERE (st.codigo = 'solicitada' AND t.solicitada_em < now() - make_interval(hours => :horas))
   OR (st.codigo = 'aceita' AND t.aceita_em < now() - make_interval(days => :dias))
ORDER BY t.solicitada_em
"""


def transferencias_paradas(conexao: Connection, *, horas: int, dias: int) -> list[dict[str, Any]]:
    linhas = conexao.execute(
        text(TRANSFERENCIAS_PARADAS), {"horas": horas, "dias": dias}
    ).mappings()
    return [dict(linha) for linha in linhas]


AJUSTES_PENDENTES = """
SELECT a.id_ajuste_estoque AS id_ajuste, a.id_loja, v.sku, p.nome AS produto, v.cor, v.tamanho,
       a.quantidade, a.motivo, solicitante.nome AS solicitante, a.solicitado_em
FROM ajuste_estoque a
JOIN loja l ON l.id_loja = a.id_loja AND l.ativa
JOIN variacao_produto v ON v.id_variacao = a.id_variacao
JOIN produto p ON p.id_produto = v.id_produto
JOIN usuario solicitante ON solicitante.id_usuario = a.id_usuario_solicitante
WHERE a.status = 'pendente'
ORDER BY a.solicitado_em
"""


def ajustes_pendentes(conexao: Connection) -> list[dict[str, Any]]:
    return [dict(linha) for linha in conexao.execute(text(AJUSTES_PENDENTES)).mappings()]


def operadores_de_estoque(conexao: Connection) -> dict[UUID, list[str]]:
    """E-mails dos operadores de estoque ativos de cada loja (quem recebe os relatorios)."""
    linhas = conexao.execute(
        text(
            """
            SELECT u.id_loja, u.email
            FROM usuario u
            JOIN tipo_usuario t
                ON t.id_tipo_usuario = u.id_tipo_usuario AND t.codigo = 'operador_estoque'
            WHERE u.ativo AND u.id_loja IS NOT NULL AND COALESCE(u.email, '') <> ''
            ORDER BY u.email
            """
        )
    ).all()
    por_loja: dict[UUID, list[str]] = {}
    for linha in linhas:
        por_loja.setdefault(linha.id_loja, []).append(linha.email)
    return por_loja


# ------------------------------------------------------------------ e-mails ao cliente (n8n)

MAX_TENTATIVAS = 5


def dados_da_compra(conexao: Connection, id_pedido: UUID) -> dict[str, Any] | None:
    """O pedido com o cliente, a loja, o pagamento e os pontos que a compra creditou."""
    linha = (
        conexao.execute(
            text(
                """
                SELECT p.id_pedido, p.numero_pedido, p.criado_em, p.valor_total, p.valor_frete,
                       p.canal_venda, l.nome AS loja, l.endereco AS loja_endereco,
                       l.cidade AS loja_cidade, u.id_usuario, u.nome, u.email,
                       (SELECT mp.nome FROM pagamento g
                         JOIN metodo_pagamento mp
                           ON mp.id_metodo_pagamento = g.id_metodo_pagamento
                         WHERE g.id_pedido = p.id_pedido
                         ORDER BY g.tentativa DESC LIMIT 1) AS pagamento,
                       COALESCE((SELECT sum(m.pontos) FROM movimento_pontos m
                                  WHERE m.id_pedido = p.id_pedido AND m.tipo = 'credito'), 0)::int
                           AS pontos_ganhos,
                       COALESCE((SELECT sum(m.pontos) FROM movimento_pontos m
                                  WHERE m.id_usuario = u.id_usuario), 0)::int AS saldo
                FROM pedido p
                JOIN loja l ON l.id_loja = p.id_loja
                JOIN usuario u ON u.id_usuario = p.id_cliente
                WHERE p.id_pedido = CAST(:p AS uuid)
                """
            ),
            {"p": str(id_pedido)},
        )
        .mappings()
        .first()
    )
    if linha is None:
        return None
    itens = conexao.execute(
        text(
            """
            SELECT pr.nome AS produto, pr.imagem_url, va.cor, va.tamanho, ip.quantidade,
                   ip.preco_unitario
            FROM item_pedido ip
            JOIN variacao_produto va ON va.id_variacao = ip.id_variacao
            JOIN produto pr ON pr.id_produto = va.id_produto
            WHERE ip.id_pedido = CAST(:p AS uuid)
            ORDER BY pr.nome, va.cor, va.tamanho
            """
        ),
        {"p": str(id_pedido)},
    ).mappings()
    return {**dict(linha), "itens": [dict(i) for i in itens]}


def reservar_aviso(conexao: Connection, id_usuario: UUID, tipo: str, chave: str) -> UUID | None:
    """Reserva o envio (status `pendente`) e devolve o id; None se ja foi enviado, se esgotou as
    tentativas ou se outro envio do mesmo aviso esta em curso. Quem chama faz o commit."""
    return conexao.execute(
        text(
            """
            INSERT INTO aviso_cliente (id_usuario, tipo, chave)
            VALUES (CAST(:u AS uuid), :tipo, :chave)
            ON CONFLICT (id_usuario, tipo, chave, canal) DO UPDATE
                SET status = 'pendente', atualizado_em = now()
                WHERE (aviso_cliente.status = 'falhou' AND aviso_cliente.tentativas < :maximo)
                   OR (aviso_cliente.status = 'pendente'
                       AND aviso_cliente.atualizado_em < now() - interval '15 minutes')
            RETURNING id_aviso
            """
        ),
        {"u": str(id_usuario), "tipo": tipo, "chave": chave, "maximo": MAX_TENTATIVAS},
    ).scalar()


def concluir_aviso(conexao: Connection, id_aviso: UUID, erro: str | None) -> None:
    conexao.execute(
        text(
            """
            UPDATE aviso_cliente SET
                status = CASE WHEN CAST(:erro AS text) IS NULL THEN 'enviado' ELSE 'falhou' END,
                tentativas = tentativas + 1,
                ultimo_erro = CAST(:erro AS text),
                enviado_em = CASE WHEN CAST(:erro AS text) IS NULL THEN now() END,
                atualizado_em = now()
            WHERE id_aviso = CAST(:a AS uuid)
            """
        ),
        {"a": str(id_aviso), "erro": erro[:300] if erro else None},
    )


def compras_a_reenviar(conexao: Connection, limite: int) -> list[UUID]:
    """Resumos de compra que falharam nos ultimos 3 dias e ainda tem tentativa."""
    return list(
        conexao.execute(
            text(
                """
                SELECT CAST(chave AS uuid) FROM aviso_cliente
                WHERE tipo = 'pos_compra' AND status = 'falhou' AND tentativas < :maximo
                  AND criado_em >= now() - interval '3 days'
                ORDER BY criado_em LIMIT :limite
                """
            ),
            {"maximo": MAX_TENTATIVAS, "limite": limite},
        ).scalars()
    )


# Cliente que aceita mensagens, com e-mail, e os creditos do ano (para a categoria).
CLIENTES_COM_EMAIL = f"""
SELECT u.id_usuario, u.nome, u.email, {SALDO_E_CREDITOS_NO_ANO}
FROM usuario u
JOIN tipo_usuario t ON t.id_tipo_usuario = u.id_tipo_usuario AND t.codigo = 'cliente'
LEFT JOIN movimento_pontos m ON m.id_usuario = u.id_usuario
WHERE u.ativo AND u.aceita_mensagens AND COALESCE(u.email, '') <> ''
GROUP BY u.id_usuario
HAVING COALESCE(sum(m.pontos), 0) > 0
ORDER BY u.nome
"""  # nosec B608


def clientes_com_email(conexao: Connection) -> list[dict[str, Any]]:
    return [dict(linha) for linha in conexao.execute(text(CLIENTES_COM_EMAIL)).mappings()]


def avisos_de_categoria(conexao: Connection, chaves: list[str]) -> set[tuple[UUID, str]]:
    """(cliente, chave) dos avisos de categoria ja enviados ou em curso."""
    if not chaves:
        return set()
    linhas = conexao.execute(
        text(
            """
            SELECT id_usuario, chave FROM aviso_cliente
            WHERE tipo = 'categoria' AND chave = ANY(:chaves) AND status <> 'falhou'
            """
        ),
        {"chaves": chaves},
    ).all()
    return {(linha.id_usuario, linha.chave) for linha in linhas}
