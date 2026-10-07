"""SQL do chat ao vivo do painel, em SQLAlchemy (`text` com parametros ligados).

Bandit B608: os textos SQL abaixo so juntam constantes deste modulo; todo valor vindo da
requisicao entra por parametro nomeado (:id, :apos, ...), nunca por concatenacao.

O escopo de loja vem do `Escopo` (montado no service a partir do token) e e aplicado em TODA
consulta e escrita: a conexao da API ignora RLS.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.chamados.repositorio import DE_ONDE, FINAIS, NO_ESCOPO, Escopo

LIMITE_TEXTO_PREVIA = 140

# Ultima mensagem da conversa e quem a mandou (equipe ou cliente).
ULTIMA_MENSAGEM = f"""
LEFT JOIN LATERAL (
    SELECT left(m.texto, {LIMITE_TEXTO_PREVIA}) AS texto, m.enviada_em,
           (t.codigo <> 'cliente') AS da_equipe
    FROM mensagem m
    JOIN usuario u ON u.id_usuario = m.id_usuario_remetente
    JOIN tipo_usuario t ON t.id_tipo_usuario = u.id_tipo_usuario
    WHERE m.id_atendimento = a.id_atendimento
    ORDER BY m.enviada_em DESC, m.id_mensagem DESC
    LIMIT 1
) ult ON true
"""  # nosec B608

# Nao lidas = mensagens do CLIENTE depois do ultimo "lido" de quem consulta.
NAO_LIDAS = """
LEFT JOIN chamado_leitura cl
    ON cl.id_atendimento = a.id_atendimento AND cl.id_usuario = CAST(:id_usuario AS uuid)
LEFT JOIN LATERAL (
    SELECT count(*) AS total
    FROM mensagem m
    JOIN usuario u ON u.id_usuario = m.id_usuario_remetente
    JOIN tipo_usuario t ON t.id_tipo_usuario = u.id_tipo_usuario
    WHERE m.id_atendimento = a.id_atendimento
      AND t.codigo = 'cliente'
      AND m.enviada_em > COALESCE(cl.lida_ate, '-infinity'::timestamptz)
) nl ON true
"""

ABERTAS = "AND st.codigo <> ALL (CAST(:finais AS text[]))"

# Fragmentos fixos escolhidos pelo codigo: o texto do usuario nunca vira SQL.
SECOES = {
    "todas": "",
    "fila": "AND a.id_usuario_responsavel IS NULL",
    "minhas": "AND a.id_usuario_responsavel = CAST(:id_usuario AS uuid)",
}


def _mapas(conexao: Connection, sql: str, parametros: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(linha) for linha in conexao.execute(text(sql), parametros).mappings()]


def _parametros(escopo: Escopo, **extra: Any) -> dict[str, Any]:
    return {**escopo.parametros(), "finais": list(FINAIS), **extra}


def _conversa(linha: dict[str, Any]) -> dict[str, Any]:
    ultima = None
    if linha["ult_em"] is not None:
        ultima = {
            "texto": linha["ult_texto"],
            "enviada_em": linha["ult_em"],
            "autor": "atendente" if linha["ult_da_equipe"] else "cliente",
        }
    return {
        "id_atendimento": linha["id_atendimento"],
        "protocolo": linha["protocolo"],
        "assunto": linha["assunto"],
        "cliente_nome": linha["cliente_nome"],
        "canal": {"codigo": linha["canal_codigo"], "nome": linha["canal_nome"]},
        "prioridade": {"codigo": linha["prioridade_codigo"], "nome": linha["prioridade_nome"]},
        "status": {"codigo": linha["status_codigo"], "nome": linha["status_nome"]},
        "id_loja": linha["id_loja"],
        "loja_nome": linha["loja_nome"],
        "aberto_em": linha["aberto_em"],
        "id_usuario_responsavel": linha["id_usuario_responsavel"],
        "responsavel_nome": linha["responsavel_nome"],
        "sou_responsavel": bool(linha["sou_responsavel"]),
        "nao_lidas": int(linha["nao_lidas"]),
        "aguardando_resposta": bool(linha["aguardando_resposta"]),
        "ultima_mensagem": ultima,
    }


# ---------------------------------------------------------------- caixa de conversas


def listar(
    conexao: Connection,
    escopo: Escopo,
    *,
    secao: str,
    apenas_nao_lidas: bool,
    limit: int,
    offset: int,
) -> tuple[int, list[dict[str, Any]]]:
    nao_lidas = "AND COALESCE(nl.total, 0) > 0" if apenas_nao_lidas else ""
    de_onde = f"{DE_ONDE} {ULTIMA_MENSAGEM} {NAO_LIDAS}"
    onde = f"WHERE {NO_ESCOPO} {ABERTAS} {SECOES[secao]} {nao_lidas}"
    parametros = _parametros(escopo)
    contagem = f"SELECT count(*) {de_onde} {onde}"  # nosec B608
    total = conexao.execute(text(contagem), parametros).scalar_one()
    linhas = _mapas(
        conexao,
        f"""
        SELECT
            a.id_atendimento, a.protocolo, COALESCE(a.assunto, ct.nome) AS assunto,
            cli.nome AS cliente_nome,
            ca.codigo AS canal_codigo, ca.nome AS canal_nome,
            pr.codigo AS prioridade_codigo, pr.nome AS prioridade_nome,
            st.codigo AS status_codigo, st.nome AS status_nome,
            a.id_loja, lj.nome AS loja_nome, a.aberto_em,
            a.id_usuario_responsavel, resp.nome AS responsavel_nome,
            (a.id_usuario_responsavel = CAST(:id_usuario AS uuid)) AS sou_responsavel,
            COALESCE(nl.total, 0) AS nao_lidas,
            COALESCE(NOT ult.da_equipe, false) AS aguardando_resposta,
            ult.texto AS ult_texto, ult.enviada_em AS ult_em, ult.da_equipe AS ult_da_equipe
        {de_onde}
        {onde}
        ORDER BY COALESCE(NOT ult.da_equipe, false) DESC, ult.enviada_em DESC NULLS LAST,
                 a.aberto_em DESC, a.id_atendimento
        LIMIT :limite OFFSET :deslocamento
        """,  # nosec B608
        {**parametros, "limite": limit, "deslocamento": offset},
    )
    return int(total), [_conversa(linha) for linha in linhas]


def resumo(conexao: Connection, escopo: Escopo) -> dict[str, int]:
    linha = (
        conexao.execute(
            text(
                f"""
                SELECT
                    count(*) FILTER (WHERE a.id_usuario_responsavel IS NULL) AS fila,
                    count(*) FILTER (
                        WHERE a.id_usuario_responsavel = CAST(:id_usuario AS uuid)
                    ) AS minhas,
                    count(*) FILTER (WHERE COALESCE(nl.total, 0) > 0) AS com_nao_lidas,
                    COALESCE(sum(nl.total), 0) AS nao_lidas,
                    count(*) FILTER (
                        WHERE COALESCE(NOT ult.da_equipe, false)
                    ) AS aguardando_resposta
                {DE_ONDE} {ULTIMA_MENSAGEM} {NAO_LIDAS}
                WHERE {NO_ESCOPO} {ABERTAS}
                """  # nosec B608
            ),
            _parametros(escopo),
        )
        .mappings()
        .one()
    )
    return {chave: int(valor) for chave, valor in linha.items()}


# ---------------------------------------------------------------- sessao e mensagens


def dados_da_sessao(conexao: Connection, escopo: Escopo, id_atendimento: UUID) -> dict[str, Any]:
    """Nome de quem consulta, ultima mensagem (cursor) e nao lidas, para abrir a conversa."""
    return _mapas(
        conexao,
        """
        SELECT
            (SELECT nome FROM usuario WHERE id_usuario = CAST(:id_usuario AS uuid)) AS meu_nome,
            (SELECT id_mensagem FROM mensagem WHERE id_atendimento = CAST(:id AS uuid)
              ORDER BY enviada_em DESC, id_mensagem DESC LIMIT 1) AS ultimo_id_mensagem,
            (SELECT count(*) FROM mensagem m
               JOIN usuario u ON u.id_usuario = m.id_usuario_remetente
               JOIN tipo_usuario t ON t.id_tipo_usuario = u.id_tipo_usuario
              WHERE m.id_atendimento = CAST(:id AS uuid) AND t.codigo = 'cliente'
                AND m.enviada_em > COALESCE((
                    SELECT lida_ate FROM chamado_leitura
                    WHERE id_atendimento = CAST(:id AS uuid)
                      AND id_usuario = CAST(:id_usuario AS uuid)
                ), '-infinity'::timestamptz)) AS nao_lidas
        """,
        {"id": str(id_atendimento), "id_usuario": str(escopo.id_usuario)},
    )[0]


def referencia_da_mensagem(
    conexao: Connection, id_atendimento: UUID, id_mensagem: UUID
) -> dict[str, Any] | None:
    achadas = _mapas(
        conexao,
        """
        SELECT enviada_em, id_mensagem FROM mensagem
        WHERE id_mensagem = CAST(:m AS uuid) AND id_atendimento = CAST(:id AS uuid)
        """,
        {"m": str(id_mensagem), "id": str(id_atendimento)},
    )
    return achadas[0] if achadas else None


_COLUNAS_MENSAGEM = """
    m.id_mensagem, m.texto, m.enviada_em, u.nome, (t.codigo <> 'cliente') AS da_equipe
    FROM mensagem m
    JOIN usuario u ON u.id_usuario = m.id_usuario_remetente
    JOIN tipo_usuario t ON t.id_tipo_usuario = u.id_tipo_usuario
"""


def _mensagem(linha: dict[str, Any]) -> dict[str, Any]:
    return {
        "id_mensagem": linha["id_mensagem"],
        "autor": "atendente" if linha["da_equipe"] else "cliente",
        "nome": linha["nome"],
        "texto": linha["texto"],
        "enviada_em": linha["enviada_em"],
    }


def mensagens_apos(
    conexao: Connection, id_atendimento: UUID, referencia: dict[str, Any], limit: int
) -> list[dict[str, Any]]:
    """O que veio DEPOIS da mensagem de referencia, em ordem (recuperacao apos uma queda)."""
    linhas = _mapas(
        conexao,
        f"""
        SELECT {_COLUNAS_MENSAGEM}
        WHERE m.id_atendimento = CAST(:id AS uuid)
          AND (m.enviada_em, m.id_mensagem)
              > (CAST(:ref_em AS timestamptz), CAST(:ref_id AS uuid))
        ORDER BY m.enviada_em, m.id_mensagem
        LIMIT :limite
        """,  # nosec B608
        {
            "id": str(id_atendimento),
            "ref_em": referencia["enviada_em"],
            "ref_id": str(referencia["id_mensagem"]),
            "limite": limit,
        },
    )
    return [_mensagem(linha) for linha in linhas]


def ultimas_mensagens(
    conexao: Connection, id_atendimento: UUID, limit: int
) -> list[dict[str, Any]]:
    """As `limit` mais recentes, devolvidas em ordem cronologica."""
    linhas = _mapas(
        conexao,
        f"""
        SELECT * FROM (
            SELECT {_COLUNAS_MENSAGEM}
            WHERE m.id_atendimento = CAST(:id AS uuid)
            ORDER BY m.enviada_em DESC, m.id_mensagem DESC
            LIMIT :limite
        ) recentes
        ORDER BY enviada_em, id_mensagem
        """,  # nosec B608
        {"id": str(id_atendimento), "limite": limit},
    )
    return [_mensagem(linha) for linha in linhas]


# ---------------------------------------------------------------- leitura


def marcar_lido(conexao: Connection, escopo: Escopo, id_atendimento: UUID) -> None:
    """Marca a conversa como lida ate agora. Nunca volta para tras (GREATEST)."""
    conexao.execute(
        text(
            """
            INSERT INTO chamado_leitura (id_usuario, id_atendimento, lida_ate)
            VALUES (CAST(:u AS uuid), CAST(:id AS uuid), now())
            ON CONFLICT (id_usuario, id_atendimento) DO UPDATE
            SET lida_ate = GREATEST(chamado_leitura.lida_ate, EXCLUDED.lida_ate),
                atualizada_em = now()
            """
        ),
        {"u": str(escopo.id_usuario), "id": str(id_atendimento)},
    )
