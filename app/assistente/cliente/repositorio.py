"""SQL do assistente: conversas, mensagens e a busca de produto por texto.

A conexao da API ignora RLS, entao toda leitura e escrita de conversa confere o dono
(`conversa_assistente.id_usuario`) contra o usuario do token.
"""

import json
import re
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection


def criar_conversa(conexao: Connection, id_usuario: UUID, tipo: str) -> dict[str, Any]:
    linha = (
        conexao.execute(
            text(
                """
                INSERT INTO conversa_assistente (id_usuario, tipo)
                VALUES (CAST(:u AS uuid), :tipo)
                RETURNING id_conversa, tipo, status, id_atendimento, criada_em
                """
            ),
            {"u": str(id_usuario), "tipo": tipo},
        )
        .mappings()
        .one()
    )
    return dict(linha)


def obter_conversa(
    conexao: Connection, id_conversa: UUID, id_usuario: UUID, *, travar: bool = False
) -> dict[str, Any] | None:
    linha = (
        conexao.execute(
            text(
                f"""
                SELECT id_conversa, tipo, status, id_atendimento, criada_em
                FROM conversa_assistente
                WHERE id_conversa = CAST(:c AS uuid) AND id_usuario = CAST(:u AS uuid)
                {"FOR UPDATE" if travar else ""}
                """  # nosec B608
            ),
            {"c": str(id_conversa), "u": str(id_usuario)},
        )
        .mappings()
        .first()
    )
    return dict(linha) if linha else None


def mensagens_visiveis(conexao: Connection, id_conversa: UUID, limite: int) -> list[dict[str, Any]]:
    """Ultimas mensagens de pessoa e assistente, em ordem (registro de ferramenta nao aparece)."""
    linhas = conexao.execute(
        text(
            """
            SELECT id_mensagem, autor, texto, criada_em,
                   COALESCE(dados->'ofertas', '[]'::jsonb) AS ofertas,
                   dados->>'avaliacao' AS avaliacao
            FROM (
                SELECT autor, texto, criada_em, dados, id_mensagem FROM mensagem_assistente
                WHERE id_conversa = CAST(:c AS uuid) AND autor IN ('usuario', 'assistente')
                ORDER BY criada_em DESC, id_mensagem DESC
                LIMIT :limite
            ) ultimas
            ORDER BY criada_em, id_mensagem
            """
        ),
        {"c": str(id_conversa), "limite": limite},
    ).mappings()
    return [dict(linha) for linha in linhas]


def gravar_mensagem(
    conexao: Connection,
    id_conversa: UUID,
    autor: str,
    texto_: str = "",
    *,
    ferramenta: str | None = None,
    dados: dict[str, Any] | None = None,
    sem_resposta: bool = False,
    modelo: str | None = None,
    tokens_entrada: int | None = None,
    tokens_saida: int | None = None,
) -> UUID:
    id_mensagem = conexao.execute(
        text(
            """
            INSERT INTO mensagem_assistente (id_conversa, autor, texto, ferramenta, dados,
                sem_resposta, modelo, tokens_entrada, tokens_saida, criada_em)
            VALUES (CAST(:c AS uuid), :autor, :texto, :ferramenta, CAST(:dados AS jsonb),
                :sem_resposta, :modelo, :te, :ts, clock_timestamp())
            RETURNING id_mensagem
            """
        ),
        {
            "c": str(id_conversa),
            "autor": autor,
            "texto": texto_,
            "ferramenta": ferramenta,
            "dados": json.dumps(dados, ensure_ascii=False, default=str)
            if dados is not None
            else None,
            "sem_resposta": sem_resposta,
            "modelo": modelo,
            "te": tokens_entrada,
            "ts": tokens_saida,
        },
    ).scalar_one()
    conexao.execute(
        text(
            "UPDATE conversa_assistente SET atualizada_em = now() "
            "WHERE id_conversa = CAST(:c AS uuid)"
        ),
        {"c": str(id_conversa)},
    )
    return id_mensagem


def contatos_do_cliente(conexao: Connection, id_usuario: UUID) -> tuple[str, str]:
    """E-mail (minusculo) e documento (so digitos) da propria conta, para reconhecer terceiros."""
    linha = conexao.execute(
        text("SELECT email, documento FROM usuario WHERE id_usuario = CAST(:u AS uuid)"),
        {"u": str(id_usuario)},
    ).first()
    if linha is None:
        return "", ""
    return (linha[0] or "").strip().lower(), re.sub(r"\D", "", linha[1] or "")


def mensagens_do_usuario_hoje(conexao: Connection, id_usuario: UUID) -> int:
    """Mensagens que a pessoa mandou ao assistente hoje (dia de Sao Paulo), em qualquer conversa."""
    return int(
        conexao.execute(
            text(
                """
                SELECT count(*) FROM mensagem_assistente m
                JOIN conversa_assistente c ON c.id_conversa = m.id_conversa
                WHERE c.id_usuario = CAST(:u AS uuid) AND m.autor = 'usuario'
                  AND m.criada_em >= date_trunc('day', now() AT TIME ZONE 'America/Sao_Paulo')
                                     AT TIME ZONE 'America/Sao_Paulo'
                """
            ),
            {"u": str(id_usuario)},
        ).scalar_one()
    )


TAMANHO_DO_TITULO = 60


def listar_conversas(
    conexao: Connection, id_usuario: UUID, tipo: str, limite: int
) -> list[dict[str, Any]]:
    """Conversas nao arquivadas, mais recentes primeiro. Titulo = comeco da primeira pergunta
    (como no assistente do vendedor, sem coluna nova)."""
    linhas = conexao.execute(
        text(
            """
            SELECT c.id_conversa, c.status, c.id_atendimento, c.criada_em, c.atualizada_em,
                   COALESCE(
                       (SELECT left(m.texto, :titulo) FROM mensagem_assistente m
                        WHERE m.id_conversa = c.id_conversa AND m.autor = 'usuario'
                        ORDER BY m.criada_em, m.id_mensagem LIMIT 1),
                       'Nova conversa'
                   ) AS titulo
            FROM conversa_assistente c
            WHERE c.id_usuario = CAST(:u AS uuid) AND c.tipo = :tipo AND c.status <> 'encerrada'
            ORDER BY c.atualizada_em DESC, c.id_conversa
            LIMIT :limite
            """
        ),
        {"u": str(id_usuario), "tipo": tipo, "limite": limite, "titulo": TAMANHO_DO_TITULO},
    ).mappings()
    return [dict(linha) for linha in linhas]


def arquivar(conexao: Connection, id_conversa: UUID, arquivada: bool) -> None:
    """Arquivar = status 'encerrada' (como no vendedor). Ao desarquivar, volta ao que era: com a
    equipe se ja tinha chamado, senao ativa."""
    conexao.execute(
        text(
            """
            UPDATE conversa_assistente
            SET status = CASE
                    WHEN :arquivada THEN 'encerrada'
                    WHEN id_atendimento IS NOT NULL THEN 'com_atendente'
                    ELSE 'ativa'
                END,
                atualizada_em = now()
            WHERE id_conversa = CAST(:c AS uuid)
            """
        ),
        {"c": str(id_conversa), "arquivada": arquivada},
    )


def avaliar_resposta(
    conexao: Connection, id_conversa: UUID, id_mensagem: UUID, avaliacao: str | None
) -> bool:
    """util / nao_util numa resposta do assistente, em `dados` (como no vendedor). False se a
    mensagem nao e uma resposta desta conversa."""
    return (
        conexao.execute(
            text(
                """
                UPDATE mensagem_assistente
                SET dados = CASE
                    WHEN CAST(:a AS text) IS NULL THEN COALESCE(dados, '{}'::jsonb) - 'avaliacao'
                    ELSE COALESCE(dados, '{}'::jsonb)
                         || jsonb_build_object('avaliacao', CAST(:a AS text))
                END
                WHERE id_mensagem = CAST(:m AS uuid) AND id_conversa = CAST(:c AS uuid)
                  AND autor = 'assistente'
                """
            ),
            {"m": str(id_mensagem), "c": str(id_conversa), "a": avaliacao},
        ).rowcount
        == 1
    )


def passar_para_atendente(conexao: Connection, id_conversa: UUID, id_atendimento: UUID) -> None:
    conexao.execute(
        text(
            """
            UPDATE conversa_assistente
            SET status = 'com_atendente', id_atendimento = CAST(:a AS uuid), atualizada_em = now()
            WHERE id_conversa = CAST(:c AS uuid)
            """
        ),
        {"c": str(id_conversa), "a": str(id_atendimento)},
    )


def _sem_acento(expressao: str) -> str:
    """Minusculas e sem acento, no SQL ("Calça" e "calca" casam)."""
    return f"translate(lower({expressao}), 'áàâãäéèêëíìîïóòôõöúùûüç', 'aaaaaeeeeiiiiooooouuuuc')"


def buscar_produtos(conexao: Connection, termos: list[str], limite: int) -> list[dict[str, Any]]:
    """Pecas ativas com estoque cujo nome, categoria, marca, tecido ou cor contem todos os termos.

    Busca por texto enquanto os embeddings (`produto.embedding`) nao sao gerados.
    """
    alvo = _sem_acento("concat_ws(' ', p.nome, p.categoria, p.marca, p.tecido, p.cores::text)")
    filtros = " AND ".join(
        f"{alvo} LIKE '%' || {_sem_acento(f'CAST(:t{i} AS text)')} || '%'"
        for i in range(len(termos))
    )
    parametros: dict[str, Any] = {f"t{i}": termo for i, termo in enumerate(termos)}
    parametros["limite"] = limite
    linhas = conexao.execute(
        text(
            f"""
            SELECT p.nome, p.categoria, p.marca, p.preco_base,
                   p.imagem_url, p.imagem_alt, p.tecido,
                   json_agg(json_build_object('id_variacao', v.id_variacao, 'sku', v.sku,
                                              'cor', v.cor, 'tamanho', v.tamanho,
                                              'preco', v.preco_venda) ORDER BY v.sku) AS variacoes
            FROM produto p
            JOIN variacao_produto v ON v.id_produto = p.id_produto AND v.ativa
            WHERE p.ativo AND {filtros}
              AND EXISTS (
                  SELECT 1 FROM estoque e JOIN loja l ON l.id_loja = e.id_loja AND l.ativa
                  WHERE e.id_variacao = v.id_variacao AND e.quantidade > 0
              )
            GROUP BY p.id_produto, p.nome, p.categoria, p.marca, p.preco_base,
                     p.imagem_url, p.imagem_alt, p.tecido
            ORDER BY p.nome
            LIMIT :limite
            """  # nosec B608
        ),
        parametros,
    ).mappings()
    return [dict(linha) for linha in linhas]


def variacao_ativa_pelo_sku(conexao: Connection, sku: str) -> UUID | None:
    return conexao.execute(
        text(
            """
            SELECT v.id_variacao
            FROM variacao_produto v JOIN produto p ON p.id_produto = v.id_produto
            WHERE upper(v.sku) = upper(:sku) AND v.ativa AND p.ativo
            """
        ),
        {"sku": sku},
    ).scalar()


def buscar_produtos_semelhantes(
    conexao: Connection, vetor: str, limite: int, distancia_maxima: float
) -> list[dict[str, Any]]:
    """Pecas ativas com estoque mais perto do vetor da pergunta (cosseno), mais proximas primeiro.

    So entram pecas que ja tem embedding (scripts/gerar_embeddings_produtos.py). `vetor` e o
    literal de `embeddings.vetor_sql`.
    """
    linhas = conexao.execute(
        text(
            """
            WITH proximos AS (
                SELECT p.id_produto,
                       p.embedding OPERATOR(extensions.<=>) CAST(:vetor AS extensions.vector)
                           AS distancia
                FROM produto p
                WHERE p.ativo AND p.embedding IS NOT NULL
                  AND EXISTS (
                      SELECT 1 FROM variacao_produto v
                      JOIN estoque e ON e.id_variacao = v.id_variacao AND e.quantidade > 0
                      JOIN loja l ON l.id_loja = e.id_loja AND l.ativa
                      WHERE v.id_produto = p.id_produto AND v.ativa
                  )
                ORDER BY distancia
                LIMIT :limite
            )
            SELECT p.nome, p.categoria, p.marca, p.preco_base, px.distancia,
                   p.imagem_url, p.imagem_alt, p.tecido,
                   json_agg(json_build_object('id_variacao', v.id_variacao, 'sku', v.sku,
                                              'cor', v.cor, 'tamanho', v.tamanho,
                                              'preco', v.preco_venda) ORDER BY v.sku) AS variacoes
            FROM proximos px
            JOIN produto p ON p.id_produto = px.id_produto
            JOIN variacao_produto v ON v.id_produto = p.id_produto AND v.ativa
            WHERE px.distancia <= :distancia_maxima
              AND EXISTS (
                  SELECT 1 FROM estoque e JOIN loja l ON l.id_loja = e.id_loja AND l.ativa
                  WHERE e.id_variacao = v.id_variacao AND e.quantidade > 0
              )
            GROUP BY p.id_produto, p.nome, p.categoria, p.marca, p.preco_base, px.distancia,
                     p.imagem_url, p.imagem_alt, p.tecido
            ORDER BY px.distancia
            """
        ),
        {"vetor": vetor, "limite": limite, "distancia_maxima": distancia_maxima},
    ).mappings()
    return [dict(linha) for linha in linhas]


def peca_para_oferta(conexao: Connection, sku: str) -> dict[str, Any] | None:
    """O cartao que o chat mostra: peca ativa, a variacao (cor, tamanho, preco), a foto e quanto
    ha em estoque nas lojas ativas. None se o SKU nao existe ou a peca saiu do catalogo."""
    linha = (
        conexao.execute(
            text(
                """
                SELECT v.id_variacao, v.sku, p.nome AS produto, p.marca, v.cor, v.tamanho,
                       v.preco_venda AS preco, p.imagem_url, p.imagem_alt, p.tecido,
                       COALESCE((
                           SELECT sum(GREATEST(e.quantidade, 0))
                           FROM estoque e JOIN loja l ON l.id_loja = e.id_loja AND l.ativa
                           WHERE e.id_variacao = v.id_variacao
                       ), 0)::int AS estoque
                FROM variacao_produto v
                JOIN produto p ON p.id_produto = v.id_produto
                WHERE upper(v.sku) = upper(:sku) AND v.ativa AND p.ativo
                """
            ),
            {"sku": sku},
        )
        .mappings()
        .first()
    )
    return dict(linha) if linha else None
