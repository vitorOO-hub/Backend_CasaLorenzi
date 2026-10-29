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
