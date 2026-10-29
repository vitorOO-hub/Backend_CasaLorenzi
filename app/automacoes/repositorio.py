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


def nome_da_loja_ativa(conexao: Connection, id_loja: UUID) -> str | None:
    return conexao.execute(
        text("SELECT nome FROM loja WHERE id_loja = :id_loja AND ativa"),
        {"id_loja": str(id_loja)},
    ).scalar_one_or_none()
