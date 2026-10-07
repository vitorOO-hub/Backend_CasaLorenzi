"""SQL da area de chamados do painel, em SQLAlchemy (`text` com parametros ligados).

Bandit B608: os textos SQL abaixo so juntam constantes deste modulo; todo valor vindo da
requisicao entra por parametro nomeado (:id, :texto, ...), nunca por concatenacao.

A conexao da API ignora RLS, entao o escopo de loja e aplicado aqui, em TODA consulta e em TODA
escrita, a partir do `Escopo` que o service monta com os dados do token.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

FINAIS = ("resolvido", "encerrado", "cancelado")
EM_ANDAMENTO = ("em_andamento", "aguardando_cliente")
RESOLVIDOS = ("resolvido", "encerrado")
PRIORIDADES_ALTAS = ("alta", "urgente")


@dataclass(frozen=True)
class Escopo:
    """Quem consulta e o que ele pode enxergar."""

    id_usuario: UUID
    id_loja: UUID | None  # None = rede inteira (admin sem filtro de loja)
    incluir_sem_loja: bool  # equipe de loja tambem atende os chamados sem loja

    def parametros(self) -> dict[str, Any]:
        return {
            "id_usuario": str(self.id_usuario),
            "id_loja": str(self.id_loja) if self.id_loja else None,
            "incluir_sem_loja": self.incluir_sem_loja,
        }


NO_ESCOPO = """
    (
        CAST(:id_loja AS uuid) IS NULL
        OR a.id_loja = CAST(:id_loja AS uuid)
        OR (CAST(:incluir_sem_loja AS boolean) AND a.id_loja IS NULL)
    )
"""

DE_ONDE = """
    FROM atendimento a
    JOIN status_atendimento st ON st.id_status_atendimento = a.id_status_atendimento
    JOIN canal_atendimento ca ON ca.id_canal_atendimento = a.id_canal_atendimento
    JOIN categoria_atendimento ct ON ct.id_categoria_atendimento = a.id_categoria_atendimento
    JOIN prioridade_atendimento pr ON pr.id_prioridade_atendimento = a.id_prioridade_atendimento
    JOIN usuario cli ON cli.id_usuario = a.id_cliente
    LEFT JOIN usuario resp ON resp.id_usuario = a.id_usuario_responsavel
    LEFT JOIN loja lj ON lj.id_loja = a.id_loja
"""

COLUNAS_ITEM = """
    a.id_atendimento,
    a.protocolo,
    COALESCE(a.assunto, ct.nome) AS assunto,
    cli.nome AS cliente_nome,
    ct.codigo AS categoria_codigo, ct.nome AS categoria_nome,
    ca.codigo AS canal_codigo, ca.nome AS canal_nome,
    pr.codigo AS prioridade_codigo, pr.nome AS prioridade_nome,
    st.codigo AS status_codigo, st.nome AS status_nome,
    a.id_loja, lj.nome AS loja_nome,
    a.aberto_em,
    a.id_usuario_responsavel, resp.nome AS responsavel_nome,
    (a.id_usuario_responsavel = CAST(:id_usuario AS uuid)) AS sou_responsavel
"""

# Fragmentos fixos escolhidos pelo codigo: o texto do usuario nunca vira SQL.
SITUACOES = {
    "abertos": "AND st.codigo <> ALL (CAST(:finais AS text[]))",
    "aberto": "AND st.codigo = 'aberto'",
    "em_andamento": "AND st.codigo = ANY (CAST(:em_andamento AS text[]))",
    "resolvido": "AND st.codigo = ANY (CAST(:resolvidos AS text[]))",
    "todos": "",
}
RESPONSAVEIS = {
    "eu": "AND a.id_usuario_responsavel = CAST(:id_usuario AS uuid)",
    "fila": "AND a.id_usuario_responsavel IS NULL",
    "todos": "",
}
# A tela mostra 3 niveis: "urgente" aparece como "Alta", entao o filtro "alta" traz os dois.
FILTRO_PRIORIDADE = {
    "baixa": ("baixa",),
    "media": ("media",),
    "alta": PRIORIDADES_ALTAS,
    "urgente": ("urgente",),
}


def _item(linha: dict[str, Any]) -> dict[str, Any]:
    return {
        "id_atendimento": linha["id_atendimento"],
        "protocolo": linha["protocolo"],
        "assunto": linha["assunto"],
        "cliente_nome": linha["cliente_nome"],
        "categoria": {"codigo": linha["categoria_codigo"], "nome": linha["categoria_nome"]},
        "canal": {"codigo": linha["canal_codigo"], "nome": linha["canal_nome"]},
        "prioridade": {"codigo": linha["prioridade_codigo"], "nome": linha["prioridade_nome"]},
        "status": {"codigo": linha["status_codigo"], "nome": linha["status_nome"]},
        "id_loja": linha["id_loja"],
        "loja_nome": linha["loja_nome"],
        "aberto_em": linha["aberto_em"],
        "id_usuario_responsavel": linha["id_usuario_responsavel"],
        "responsavel_nome": linha["responsavel_nome"],
        "sou_responsavel": bool(linha["sou_responsavel"]),
    }


def _mapas(conexao: Connection, sql: str, parametros: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(linha) for linha in conexao.execute(text(sql), parametros).mappings()]


# ---------------------------------------------------------------- identidade


def id_usuario_ativo(conexao: Connection, id_auth: UUID) -> UUID | None:
    """Linha de `usuario` (ativa) ligada a conta do Supabase Auth."""
    return conexao.execute(
        text("SELECT id_usuario FROM usuario WHERE auth_user_id = CAST(:a AS uuid) AND ativo"),
        {"a": str(id_auth)},
    ).scalar()


# ---------------------------------------------------------------- leituras


_OPCOES = {
    "status": "SELECT codigo, nome FROM status_atendimento WHERE ativo ORDER BY ordem",
    "canais": "SELECT codigo, nome FROM canal_atendimento WHERE ativo ORDER BY ordem",
    "categorias": "SELECT codigo, nome FROM categoria_atendimento WHERE ativo ORDER BY ordem",
    "prioridades": "SELECT codigo, nome FROM prioridade_atendimento WHERE ativo ORDER BY ordem",
}


def opcoes(conexao: Connection, escopo: Escopo, *, todas_as_lojas: bool) -> dict[str, Any]:
    lojas = _mapas(
        conexao,
        """
        SELECT id_loja, nome FROM loja
        WHERE ativa AND (CAST(:todas AS boolean) OR id_loja = CAST(:id_loja AS uuid))
        ORDER BY nome
        """,
        {"todas": todas_as_lojas, "id_loja": str(escopo.id_loja) if escopo.id_loja else None},
    )
    return {
        **{chave: _mapas(conexao, sql, {}) for chave, sql in _OPCOES.items()},
        "lojas": lojas,
    }


def resumo(conexao: Connection, escopo: Escopo) -> dict[str, Any]:
    linha = (
        conexao.execute(
            text(
                f"""
                SELECT
                    count(*) FILTER (WHERE st.codigo = 'aberto') AS sem_resposta,
                    count(*) FILTER (WHERE st.codigo = ANY (CAST(:em_andamento AS text[])))
                        AS em_andamento,
                    count(*) FILTER (
                        WHERE st.codigo <> ALL (CAST(:finais AS text[]))
                          AND pr.codigo = ANY (CAST(:altas AS text[]))
                    ) AS prioridade_alta,
                    count(*) FILTER (WHERE st.codigo = ANY (CAST(:resolvidos AS text[])))
                        AS resolvidos,
                    count(*) FILTER (
                        WHERE st.codigo <> ALL (CAST(:finais AS text[]))
                          AND a.id_usuario_responsavel IS NULL
                    ) AS na_fila,
                    count(*) FILTER (
                        WHERE st.codigo <> ALL (CAST(:finais AS text[]))
                          AND a.id_usuario_responsavel = CAST(:id_usuario AS uuid)
                    ) AS meus
                {DE_ONDE}
                WHERE {NO_ESCOPO}
                """  # nosec B608
            ),
            {
                **escopo.parametros(),
                "finais": list(FINAIS),
                "em_andamento": list(EM_ANDAMENTO),
                "resolvidos": list(RESOLVIDOS),
                "altas": list(PRIORIDADES_ALTAS),
            },
        )
        .mappings()
        .one()
    )
    return {chave: int(valor) for chave, valor in linha.items()}


def listar(
    conexao: Connection,
    escopo: Escopo,
    *,
    situacao: str,
    responsavel: str,
    prioridade: str | None,
    canal: str | None,
    categoria: str | None,
    limit: int,
    offset: int,
) -> tuple[int, list[dict[str, Any]]]:
    filtros = f"""
        WHERE {NO_ESCOPO}
        {SITUACOES[situacao]}
        {RESPONSAVEIS[responsavel]}
        AND (CAST(:prioridades AS text[]) IS NULL OR pr.codigo = ANY (CAST(:prioridades AS text[])))
        AND (CAST(:canal AS text) IS NULL OR ca.codigo = CAST(:canal AS text))
        AND (CAST(:categoria AS text) IS NULL OR ct.codigo = CAST(:categoria AS text))
    """  # nosec B608
    parametros = {
        **escopo.parametros(),
        "finais": list(FINAIS),
        "em_andamento": list(EM_ANDAMENTO),
        "resolvidos": list(RESOLVIDOS),
        "prioridades": list(FILTRO_PRIORIDADE[prioridade]) if prioridade else None,
        "canal": canal,
        "categoria": categoria,
    }
    total = conexao.execute(text(f"SELECT count(*) {DE_ONDE} {filtros}"), parametros).scalar_one()  # nosec B608
    linhas = _mapas(
        conexao,
        f"""
        SELECT {COLUNAS_ITEM}
        {DE_ONDE}
        {filtros}
        ORDER BY pr.ordem DESC, a.aberto_em DESC, a.id_atendimento
        LIMIT :limite OFFSET :deslocamento
        """,  # nosec B608
        {**parametros, "limite": limit, "deslocamento": offset},
    )
    return int(total), [_item(linha) for linha in linhas]


def obter_item(conexao: Connection, escopo: Escopo, id_atendimento: UUID) -> dict[str, Any] | None:
    linhas = _mapas(
        conexao,
        f"""
        SELECT {COLUNAS_ITEM}
        {DE_ONDE}
        WHERE a.id_atendimento = CAST(:id AS uuid) AND {NO_ESCOPO}
        """,  # nosec B608
        {**escopo.parametros(), "id": str(id_atendimento)},
    )
    return _item(linhas[0]) if linhas else None


def obter_detalhe(
    conexao: Connection, escopo: Escopo, id_atendimento: UUID, *, ver_compras: bool
) -> dict[str, Any] | None:
    item = obter_item(conexao, escopo, id_atendimento)
    if item is None:
        return None
    id_param = {"id": str(id_atendimento)}

    cliente = _mapas(
        conexao,
        """
        SELECT cli.id_usuario AS id_cliente, cli.nome, cli.email, cli.telefone, cli.cidade,
               cli.criado_em AS cliente_desde, a.id_pedido
        FROM atendimento a JOIN usuario cli ON cli.id_usuario = a.id_cliente
        WHERE a.id_atendimento = CAST(:id AS uuid)
        """,
        id_param,
    )[0]
    id_pedido = cliente.pop("id_pedido")

    pedido = None
    if id_pedido:
        achados = _mapas(
            conexao,
            """
            SELECT p.id_pedido, p.numero_pedido, sp.nome AS status
            FROM pedido p JOIN status_pedido sp ON sp.id_status_pedido = p.id_status_pedido
            WHERE p.id_pedido = CAST(:p AS uuid)
            """,
            {"p": str(id_pedido)},
        )
        pedido = achados[0] if achados else None

    pecas = _mapas(
        conexao,
        """
        SELECT pd.nome, v.sku, v.cor, v.tamanho
        FROM atendimento_item ai
        JOIN item_pedido ip ON ip.id_item_pedido = ai.id_item_pedido
        JOIN variacao_produto v ON v.id_variacao = ip.id_variacao
        JOIN produto pd ON pd.id_produto = v.id_produto
        WHERE ai.id_atendimento = CAST(:id AS uuid)
        ORDER BY pd.nome, v.sku
        """,
        id_param,
    )
    anexos = _mapas(
        conexao,
        """
        SELECT id_anexo, nome, caminho, criado_em FROM chamado_anexo
        WHERE id_atendimento = CAST(:id AS uuid) ORDER BY criado_em, id_anexo
        """,
        id_param,
    )
    outros = _mapas(
        conexao,
        f"""
        SELECT a.id_atendimento, a.protocolo, COALESCE(a.assunto, ct.nome) AS assunto,
               st.codigo AS status_codigo, st.nome AS status_nome
        {DE_ONDE}
        WHERE a.id_cliente = CAST(:cliente AS uuid)
          AND a.id_atendimento <> CAST(:id AS uuid)
          AND {NO_ESCOPO}
        ORDER BY a.aberto_em DESC
        LIMIT 10
        """,  # nosec B608
        {**escopo.parametros(), **id_param, "cliente": str(cliente["id_cliente"])},
    )
    compras = None
    if ver_compras:
        compras = _mapas(
            conexao,
            """
            SELECT id_pedido, numero_pedido, criado_em, valor_total FROM pedido
            WHERE id_cliente = CAST(:cliente AS uuid)
              AND (CAST(:id_loja AS uuid) IS NULL OR id_loja = CAST(:id_loja AS uuid))
            ORDER BY criado_em DESC
            LIMIT 4
            """,
            {"cliente": str(cliente["id_cliente"]), "id_loja": escopo.parametros()["id_loja"]},
        )
    return {
        **item,
        "cliente": cliente,
        "pedido": pedido,
        "pecas": pecas,
        "anexos": anexos,
        "outros_chamados": [
            {
                "id_atendimento": o["id_atendimento"],
                "protocolo": o["protocolo"],
                "assunto": o["assunto"],
                "status": {"codigo": o["status_codigo"], "nome": o["status_nome"]},
            }
            for o in outros
        ],
        "compras_recentes": compras,
    }


def mensagens(conexao: Connection, id_atendimento: UUID) -> list[dict[str, Any]]:
    """Quem chama ja confirmou que o chamado esta no escopo."""
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


# ---------------------------------------------------------------- escritas


def travar(conexao: Connection, escopo: Escopo, id_atendimento: UUID) -> dict[str, Any] | None:
    """Trava o chamado (so se estiver no escopo) ate o fim da transacao e le o estado atual.

    A trava e pedida SEM junções de proposito: depois de esperar outra transacao, o PostgreSQL
    reavalia o WHERE e as junções com a versao nova da linha, e um JOIN pelo status (que acabou de
    mudar) faria quem perdeu a corrida ver "nao encontrado" em vez de "ja foi assumido". Com a linha
    ja travada, a segunda consulta enxerga o estado confirmado.
    """
    travado = conexao.execute(
        text(
            f"""
            SELECT a.id_atendimento FROM atendimento a
            WHERE a.id_atendimento = CAST(:id AS uuid) AND {NO_ESCOPO}
            FOR UPDATE
            """  # nosec B608
        ),
        {**escopo.parametros(), "id": str(id_atendimento)},
    ).first()
    if travado is None:
        return None
    linhas = _mapas(
        conexao,
        f"""
        SELECT a.id_atendimento, st.codigo AS status_codigo,
               a.id_usuario_responsavel, resp.nome AS responsavel_nome
        {DE_ONDE}
        WHERE a.id_atendimento = CAST(:id AS uuid)
        """,  # nosec B608
        {"id": str(id_atendimento)},
    )
    return linhas[0] if linhas else None


def gravar_mensagem(
    conexao: Connection, id_atendimento: UUID, id_usuario: UUID, texto: str
) -> UUID:
    return conexao.execute(
        text(
            """
            INSERT INTO mensagem (id_atendimento, id_usuario_remetente, texto)
            VALUES (CAST(:id AS uuid), CAST(:u AS uuid), :texto)
            RETURNING id_mensagem
            """
        ),
        {"id": str(id_atendimento), "u": str(id_usuario), "texto": texto},
    ).scalar_one()


def registrar_resposta(conexao: Connection, id_atendimento: UUID, id_usuario: UUID) -> None:
    """Primeira resposta da equipe: assume (se ninguem assumiu) e tira o chamado de 'aberto'."""
    conexao.execute(
        text(
            """
            UPDATE atendimento
            SET id_usuario_responsavel = COALESCE(id_usuario_responsavel, CAST(:u AS uuid)),
                id_status_atendimento = CASE
                    WHEN id_status_atendimento = (
                        SELECT id_status_atendimento FROM status_atendimento WHERE codigo = 'aberto'
                    ) THEN (
                        SELECT id_status_atendimento FROM status_atendimento
                        WHERE codigo = 'em_andamento'
                    )
                    ELSE id_status_atendimento
                END
            WHERE id_atendimento = CAST(:id AS uuid)
            """
        ),
        {"id": str(id_atendimento), "u": str(id_usuario)},
    )


def assumir(conexao: Connection, id_atendimento: UUID, id_usuario: UUID) -> None:
    conexao.execute(
        text(
            """
            UPDATE atendimento
            SET id_usuario_responsavel = CAST(:u AS uuid),
                id_status_atendimento = (
                    SELECT id_status_atendimento FROM status_atendimento
                    WHERE codigo = 'em_andamento'
                )
            WHERE id_atendimento = CAST(:id AS uuid)
            """
        ),
        {"id": str(id_atendimento), "u": str(id_usuario)},
    )


def resolver(conexao: Connection, id_atendimento: UUID) -> None:
    conexao.execute(
        text(
            """
            UPDATE atendimento
            SET id_status_atendimento = (
                    SELECT id_status_atendimento FROM status_atendimento WHERE codigo = 'resolvido'
                ),
                encerrado_em = now()
            WHERE id_atendimento = CAST(:id AS uuid)
            """
        ),
        {"id": str(id_atendimento)},
    )
