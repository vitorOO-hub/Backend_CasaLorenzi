"""Transferencias e reposicoes entre lojas no painel de estoque.

Fluxo: o destino pede -> a origem aceita (a peca SAI do estoque dela) -> o destino confirma o
recebimento (a peca ENTRA no dele). A origem pode recusar. Reposicao e um pedido a rede toda
(sem origem): a primeira outra loja que atende vira a origem. Cada passo trava a transferencia e a
linha do estoque que vai mexer, entao dois cliques ao mesmo tempo nunca movem a peca duas vezes.

Bandit B608: os textos SQL juntam so constantes deste modulo; valores entram por parametro.
"""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.chamados.repositorio import id_usuario_ativo
from app.core.erros_auth import SemPermissao
from app.core.papeis import UsuarioAtual
from app.painel_estoque import repositorio_escrita as escrita
from app.painel_estoque import service
from app.painel_estoque.erros import (
    LojaInvalida,
    LojaObrigatoria,
    PecaNaoEncontrada,
    SaldoInsuficiente,
    SemPermissaoNaTransferencia,
    TransferenciaJaDecidida,
    TransferenciaNaoEncontrada,
)

# ---------------------------------------------------------------- corpos e respostas

Observacao = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]
Sku = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]


class _Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NovaTransferencia(_Entrada):
    sku: Sku
    quantidade: int = Field(ge=1, le=100_000, strict=True)
    id_loja_origem: UUID
    observacao: Observacao | None = None
    # So o admin informa a loja que pede; para os demais vale a do token.
    id_loja: UUID | None = None


class NovaReposicao(_Entrada):
    sku: Sku
    quantidade: int = Field(ge=1, le=100_000, strict=True)
    observacao: Observacao | None = None
    id_loja: UUID | None = None


class Decisao(_Entrada):
    """Corpo opcional de aceitar/recusar/receber. O admin diz por qual loja age (reposicao)."""

    motivo: Observacao | None = None
    id_loja: UUID | None = None


class _Saida(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ItemTransferencia(_Saida):
    id_transferencia: UUID
    # transferencia | reposicao_rede
    tipo: str
    # solicitada | aceita | recebida | recusada
    status: str
    solicitada_em: datetime
    aceita_em: datetime | None
    recebida_em: datetime | None
    id_loja_origem: UUID | None
    origem_nome: str | None
    id_loja_destino: UUID
    destino_nome: str
    sku: str
    produto: str
    cor: str
    tamanho: str
    quantidade: int
    observacao: str | None
    motivo_recusa: str | None
    solicitante: str
    responsavel: str | None
    # O que quem esta olhando pode fazer agora: aceitar, recusar, receber.
    acoes: list[str]


class Transferencias(_Saida):
    total: int
    # Quantas esperam uma acao de quem consulta (selo da aba), independente do filtro.
    aguardando_voce: int
    itens: list[ItemTransferencia]


# ---------------------------------------------------------------- consultas

LISTA_DE = """
FROM transferencia_estoque t
JOIN tipo_transferencia_estoque tipo
    ON tipo.id_tipo_transferencia_estoque = t.id_tipo_transferencia_estoque
JOIN status_transferencia_estoque st
    ON st.id_status_transferencia_estoque = t.id_status_transferencia_estoque
LEFT JOIN loja origem ON origem.id_loja = t.id_loja_origem
JOIN loja destino ON destino.id_loja = t.id_loja_destino
JOIN variacao_produto v ON v.id_variacao = t.id_variacao
JOIN produto ON produto.id_produto = v.id_produto
JOIN usuario solicitante ON solicitante.id_usuario = t.id_usuario_solicitante
LEFT JOIN usuario responsavel ON responsavel.id_usuario = t.id_usuario_responsavel
WHERE (
        CAST(:id_loja AS uuid) IS NULL
        OR t.id_loja_origem = CAST(:id_loja AS uuid)
        OR t.id_loja_destino = CAST(:id_loja AS uuid)
        OR (tipo.codigo = 'reposicao_rede' AND t.id_loja_origem IS NULL)
    )
  AND (CAST(:tipo AS text) IS NULL OR tipo.codigo = CAST(:tipo AS text))
  AND (CAST(:id_transferencia AS uuid) IS NULL
       OR t.id_transferencia_estoque = CAST(:id_transferencia AS uuid))
"""
# A etapa em que a loja de quem consulta precisa agir.
AGUARDA_A_LOJA = """
  AND (
      CAST(:id_loja AS uuid) IS NULL AND st.codigo IN ('solicitada', 'aceita')
      OR (
          st.codigo = 'solicitada'
          AND (t.id_loja_origem = CAST(:id_loja AS uuid)
               OR (t.id_loja_origem IS NULL AND t.id_loja_destino <> CAST(:id_loja AS uuid)))
      )
      OR (st.codigo = 'aceita' AND t.id_loja_destino = CAST(:id_loja AS uuid))
  )
"""
EM_ANDAMENTO = "  AND st.codigo IN ('solicitada', 'aceita')\n"
SELECAO = """
SELECT
    t.id_transferencia_estoque AS id_transferencia,
    tipo.codigo AS tipo,
    st.codigo AS status,
    t.solicitada_em,
    t.aceita_em,
    t.recebida_em,
    t.id_loja_origem,
    origem.nome AS origem_nome,
    t.id_loja_destino,
    destino.nome AS destino_nome,
    v.sku,
    produto.nome AS produto,
    v.cor,
    v.tamanho,
    t.quantidade,
    t.observacao,
    t.motivo_recusa,
    solicitante.nome AS solicitante,
    responsavel.nome AS responsavel
"""
ORDEM = " ORDER BY t.solicitada_em DESC, t.id_transferencia_estoque DESC"
PAGINA = " LIMIT :limite OFFSET :deslocamento"
CONTAGEM = "SELECT count(*) " + LISTA_DE  # nosec B608
CONTAGEM_AGUARDANDO = "SELECT count(*) " + LISTA_DE + AGUARDA_A_LOJA  # nosec B608
SQL_DA_LISTA = {
    "todas": SELECAO + LISTA_DE + ORDEM + PAGINA,  # nosec B608
    "andamento": SELECAO + LISTA_DE + EM_ANDAMENTO + ORDEM + PAGINA,  # nosec B608
    "acao": SELECAO + LISTA_DE + AGUARDA_A_LOJA + ORDEM + PAGINA,  # nosec B608
}
CONTAGEM_DA_LISTA = {
    "todas": CONTAGEM,
    "andamento": CONTAGEM + EM_ANDAMENTO,  # nosec B608
    "acao": CONTAGEM_AGUARDANDO,
}


def acoes_para(linha: dict[str, Any], id_loja: UUID | None) -> list[str]:
    """O que a loja de quem consulta pode fazer com a transferencia (admin: tudo da etapa)."""
    status, origem, destino = linha["status"], linha["id_loja_origem"], linha["id_loja_destino"]
    if status == "solicitada":
        if id_loja is None:
            return ["aceitar", "recusar"]
        if origem == id_loja or (origem is None and destino != id_loja):
            return ["aceitar", "recusar"]
    if status == "aceita" and (id_loja is None or destino == id_loja):
        return ["receber"]
    return []


def listar(
    conexao: Connection,
    *,
    id_loja: UUID | None,
    situacao: str,
    tipo: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    parametros = {
        "id_loja": str(id_loja) if id_loja else None,
        "tipo": tipo,
        "id_transferencia": None,
    }
    total = conexao.execute(text(CONTAGEM_DA_LISTA[situacao]), parametros).scalar_one()
    aguardando = conexao.execute(text(CONTAGEM_AGUARDANDO), parametros).scalar_one()
    linhas = conexao.execute(
        text(SQL_DA_LISTA[situacao]), {**parametros, "limite": limit, "deslocamento": offset}
    ).mappings()
    itens = [{**dict(linha), "acoes": acoes_para(dict(linha), id_loja)} for linha in linhas]
    return {"total": int(total), "aguardando_voce": int(aguardando), "itens": itens}


def _item(conexao: Connection, id_transferencia: UUID, id_loja: UUID | None) -> dict[str, Any]:
    parametros = {"id_loja": None, "tipo": None, "id_transferencia": str(id_transferencia)}
    linha = (
        conexao.execute(text(SQL_DA_LISTA["todas"]), {**parametros, "limite": 1, "deslocamento": 0})
        .mappings()
        .one()
    )
    return {**dict(linha), "acoes": acoes_para(dict(linha), id_loja)}


# ---------------------------------------------------------------- regras

PAPEIS = service.PAPEIS_DO_ESTOQUE


def _quem_e_onde(
    conexao: Connection, usuario: UsuarioAtual, id_loja_pedida: UUID | None
) -> tuple[UUID, UUID | None]:
    """(id do usuario no banco, loja de quem age; None para o admin sem loja informada)."""
    loja = service.loja_do_escopo(usuario, id_loja_pedida)
    id_usuario = id_usuario_ativo(conexao, usuario.id_auth)
    if id_usuario is None:
        raise SemPermissao()
    return id_usuario, loja


def _loja_ativa(conexao: Connection, id_loja: UUID) -> bool:
    return bool(
        conexao.execute(
            text("SELECT 1 FROM loja WHERE id_loja = CAST(:id AS uuid) AND ativa"),
            {"id": str(id_loja)},
        ).first()
    )


def _criar(
    conexao: Connection,
    *,
    tipo: str,
    id_usuario: UUID,
    destino: UUID,
    origem: UUID | None,
    sku: str,
    quantidade: int,
    observacao: str | None,
) -> UUID:
    id_variacao = escrita.achar_peca(conexao, sku)
    if id_variacao is None:
        raise PecaNaoEncontrada()
    return conexao.execute(
        text(
            """
            INSERT INTO transferencia_estoque (
                id_tipo_transferencia_estoque, id_status_transferencia_estoque,
                id_loja_origem, id_loja_destino, id_variacao, id_usuario_solicitante,
                quantidade, observacao)
            VALUES (
                (SELECT id_tipo_transferencia_estoque FROM tipo_transferencia_estoque
                 WHERE codigo = :tipo),
                (SELECT id_status_transferencia_estoque FROM status_transferencia_estoque
                 WHERE codigo = 'solicitada'),
                CAST(:origem AS uuid), CAST(:destino AS uuid), CAST(:variacao AS uuid),
                CAST(:solicitante AS uuid), :quantidade, :observacao)
            RETURNING id_transferencia_estoque
            """
        ),
        {
            "tipo": tipo,
            "origem": str(origem) if origem else None,
            "destino": str(destino),
            "variacao": str(id_variacao),
            "solicitante": str(id_usuario),
            "quantidade": quantidade,
            "observacao": observacao or None,
        },
    ).scalar_one()


def solicitar(
    conexao: Connection, usuario: UsuarioAtual, dados: NovaTransferencia
) -> dict[str, Any]:
    id_usuario, destino = _quem_e_onde(conexao, usuario, dados.id_loja)
    if destino is None:
        raise LojaObrigatoria()
    if dados.id_loja_origem == destino or not _loja_ativa(conexao, dados.id_loja_origem):
        raise LojaInvalida()
    novo = _criar(
        conexao,
        tipo="transferencia",
        id_usuario=id_usuario,
        destino=destino,
        origem=dados.id_loja_origem,
        sku=dados.sku,
        quantidade=dados.quantidade,
        observacao=dados.observacao,
    )
    conexao.commit()
    return _item(conexao, novo, destino)


def pedir_reposicao(
    conexao: Connection, usuario: UsuarioAtual, dados: NovaReposicao
) -> dict[str, Any]:
    id_usuario, destino = _quem_e_onde(conexao, usuario, dados.id_loja)
    if destino is None:
        raise LojaObrigatoria()
    novo = _criar(
        conexao,
        tipo="reposicao_rede",
        id_usuario=id_usuario,
        destino=destino,
        origem=None,
        sku=dados.sku,
        quantidade=dados.quantidade,
        observacao=dados.observacao,
    )
    conexao.commit()
    return _item(conexao, novo, destino)


def _travar(conexao: Connection, id_transferencia: UUID) -> dict[str, Any] | None:
    """Trava a transferencia (sem junções, para quem perde a corrida ver o estado novo)."""
    travada = conexao.execute(
        text(
            "SELECT id_transferencia_estoque FROM transferencia_estoque "
            "WHERE id_transferencia_estoque = CAST(:id AS uuid) FOR UPDATE"
        ),
        {"id": str(id_transferencia)},
    ).first()
    if travada is None:
        return None
    linha = (
        conexao.execute(
            text(
                """
            SELECT t.id_loja_origem, t.id_loja_destino, t.id_variacao, t.quantidade,
                   st.codigo AS status, tipo.codigo AS tipo, destino.nome AS destino_nome
            FROM transferencia_estoque t
            JOIN status_transferencia_estoque st
                ON st.id_status_transferencia_estoque = t.id_status_transferencia_estoque
            JOIN tipo_transferencia_estoque tipo
                ON tipo.id_tipo_transferencia_estoque = t.id_tipo_transferencia_estoque
            JOIN loja destino ON destino.id_loja = t.id_loja_destino
            WHERE t.id_transferencia_estoque = CAST(:id AS uuid)
            """
            ),
            {"id": str(id_transferencia)},
        )
        .mappings()
        .one()
    )
    return dict(linha)


def _visivel(t: dict[str, Any], loja: UUID | None) -> bool:
    if loja is None:
        return True
    aberta = t["tipo"] == "reposicao_rede" and t["id_loja_origem"] is None
    return loja in (t["id_loja_origem"], t["id_loja_destino"]) or aberta


def _quem_atende(t: dict[str, Any], loja: UUID | None, id_loja_corpo: UUID | None) -> UUID:
    """Loja que aceita ou recusa: a origem; na reposicao aberta, qualquer outra que nao pediu."""
    if t["id_loja_origem"] is not None:
        atuante = t["id_loja_origem"] if loja is None else loja
        if atuante != t["id_loja_origem"]:
            raise SemPermissaoNaTransferencia()
        return atuante
    atuante = loja if loja is not None else id_loja_corpo
    if atuante is None:
        raise LojaObrigatoria()
    if atuante == t["id_loja_destino"]:
        raise SemPermissaoNaTransferencia()
    return atuante


def _abrir(
    conexao: Connection, usuario: UsuarioAtual, id_transferencia: UUID, etapa: str
) -> tuple[UUID, UUID | None, dict[str, Any]]:
    """Valida quem, trava e confere a etapa. Devolve (usuario, loja de quem age, transferencia)."""
    id_usuario = id_usuario_ativo(conexao, usuario.id_auth)
    if id_usuario is None or usuario.papel not in PAPEIS:
        raise SemPermissao()
    loja = service.loja_do_escopo(usuario, None)
    t = _travar(conexao, id_transferencia)
    if t is None or not _visivel(t, loja):
        raise TransferenciaNaoEncontrada()
    if t["status"] != etapa:
        raise TransferenciaJaDecidida()
    return id_usuario, loja, t


def aceitar(
    conexao: Connection, usuario: UsuarioAtual, id_transferencia: UUID, dados: Decisao
) -> dict[str, Any]:
    """A origem aceita: a peca sai do estoque dela agora (e fica em transito ate o recebimento)."""
    id_usuario, loja, t = _abrir(conexao, usuario, id_transferencia, "solicitada")
    atuante = _quem_atende(t, loja, dados.id_loja)
    if t["id_loja_origem"] is None and not _loja_ativa(conexao, atuante):
        raise LojaInvalida()
    saldo = escrita.travar_estoque(conexao, atuante, t["id_variacao"]) or 0
    if saldo < t["quantidade"]:
        raise SaldoInsuficiente(saldo)
    escrita.gravar_movimentacao(
        conexao,
        id_loja=atuante,
        id_variacao=t["id_variacao"],
        id_usuario=id_usuario,
        tipo="transferencia_saida",
        quantidade=t["quantidade"],
        anterior=saldo,
        posterior=saldo - t["quantidade"],
        motivo=f"Transferência para {t['destino_nome']}",
    )
    conexao.execute(
        text(
            """
            UPDATE transferencia_estoque
            SET id_status_transferencia_estoque = (
                    SELECT id_status_transferencia_estoque FROM status_transferencia_estoque
                    WHERE codigo = 'aceita'),
                id_loja_origem = CAST(:origem AS uuid),
                id_usuario_responsavel = CAST(:usuario AS uuid),
                aceita_em = now(), atualizada_em = now()
            WHERE id_transferencia_estoque = CAST(:id AS uuid)
            """
        ),
        {"origem": str(atuante), "usuario": str(id_usuario), "id": str(id_transferencia)},
    )
    conexao.commit()
    return _item(conexao, id_transferencia, loja)


def recusar(
    conexao: Connection, usuario: UsuarioAtual, id_transferencia: UUID, dados: Decisao
) -> dict[str, Any]:
    id_usuario, loja, t = _abrir(conexao, usuario, id_transferencia, "solicitada")
    _quem_atende(t, loja, dados.id_loja)
    conexao.execute(
        text(
            """
            UPDATE transferencia_estoque
            SET id_status_transferencia_estoque = (
                    SELECT id_status_transferencia_estoque FROM status_transferencia_estoque
                    WHERE codigo = 'recusada'),
                id_usuario_responsavel = CAST(:usuario AS uuid),
                motivo_recusa = :motivo, atualizada_em = now()
            WHERE id_transferencia_estoque = CAST(:id AS uuid)
            """
        ),
        {"usuario": str(id_usuario), "motivo": dados.motivo or None, "id": str(id_transferencia)},
    )
    conexao.commit()
    return _item(conexao, id_transferencia, loja)


def receber(conexao: Connection, usuario: UsuarioAtual, id_transferencia: UUID) -> dict[str, Any]:
    """O destino confirma a chegada: a peca entra no estoque dele."""
    id_usuario, loja, t = _abrir(conexao, usuario, id_transferencia, "aceita")
    if loja is not None and loja != t["id_loja_destino"]:
        raise SemPermissaoNaTransferencia()
    destino = t["id_loja_destino"]
    saldo = escrita.travar_estoque(conexao, destino, t["id_variacao"])
    if saldo is None:
        escrita.criar_linha_de_estoque(conexao, destino, t["id_variacao"])
        saldo = escrita.travar_estoque(conexao, destino, t["id_variacao"]) or 0
    origem_nome = conexao.execute(
        text("SELECT nome FROM loja WHERE id_loja = CAST(:id AS uuid)"),
        {"id": str(t["id_loja_origem"])},
    ).scalar()
    escrita.gravar_movimentacao(
        conexao,
        id_loja=destino,
        id_variacao=t["id_variacao"],
        id_usuario=id_usuario,
        tipo="transferencia_entrada",
        quantidade=t["quantidade"],
        anterior=saldo,
        posterior=saldo + t["quantidade"],
        motivo=f"Transferência recebida de {origem_nome}",
    )
    conexao.execute(
        text(
            """
            UPDATE transferencia_estoque
            SET id_status_transferencia_estoque = (
                    SELECT id_status_transferencia_estoque FROM status_transferencia_estoque
                    WHERE codigo = 'recebida'),
                id_usuario_recebedor = CAST(:usuario AS uuid),
                recebida_em = now(), atualizada_em = now()
            WHERE id_transferencia_estoque = CAST(:id AS uuid)
            """
        ),
        {"usuario": str(id_usuario), "id": str(id_transferencia)},
    )
    conexao.commit()
    return _item(conexao, id_transferencia, loja)


def listar_do_usuario(
    conexao: Connection,
    usuario: UsuarioAtual,
    *,
    id_loja: UUID | None,
    situacao: Literal["acao", "andamento", "todas"],
    tipo: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    loja = service.loja_do_escopo(usuario, id_loja)
    return listar(conexao, id_loja=loja, situacao=situacao, tipo=tipo, limit=limit, offset=offset)
