"""Busca semantica contra o pgvector de verdade (vetores sinteticos, sem chamar o Gemini)."""

from uuid import uuid4

import pytest
from sqlalchemy import text

from app.assistente.cliente import embeddings, repositorio

pytestmark = pytest.mark.banco


def _vetor(eixo: int) -> list[float]:
    """Vetor unitario num eixo: dois eixos diferentes ficam a distancia 1 (ortogonais)."""
    v = [0.0] * embeddings.DIMENSOES
    v[eixo] = 1.0
    return v


def _peca(conexao, nome, *, com_estoque=True):
    id_produto = conexao.execute(
        text("INSERT INTO produto (nome, preco_base) VALUES (:n, 100) RETURNING id_produto"),
        {"n": nome},
    ).scalar_one()
    id_variacao = conexao.execute(
        text(
            "INSERT INTO variacao_produto (id_produto, sku, cor, tamanho, preco_venda) "
            "VALUES (:p, :s, 'azul', 'M', 100) RETURNING id_variacao"
        ),
        {"p": id_produto, "s": f"EMB-{uuid4().hex[:8]}"},
    ).scalar_one()
    if com_estoque:
        loja = conexao.execute(
            text("INSERT INTO loja (codigo, nome, ativa) VALUES (:c, :n, true) RETURNING id_loja"),
            {"c": f"E{uuid4().hex[:8]}", "n": f"loja {uuid4().hex[:6]}"},
        ).scalar_one()
        conexao.execute(
            text("INSERT INTO estoque (id_loja, id_variacao, quantidade) VALUES (:l, :v, 2)"),
            {"l": loja, "v": id_variacao},
        )
    return id_produto


class GeradorFalso:
    def __init__(self):
        self.textos = []

    def documentos(self, textos):
        self.textos.extend(textos)
        return [_vetor(i) for i in range(len(textos))]


def test_pendentes_gravacao_e_busca_por_semelhanca(sa_conn):
    terno = _peca(sa_conn, f"Terno {uuid4().hex[:6]}")
    camisa = _peca(sa_conn, f"Camisa {uuid4().hex[:6]}")
    sem_estoque = _peca(sa_conn, f"Bermuda {uuid4().hex[:6]}", com_estoque=False)

    pendentes = {p["id_produto"] for p in embeddings.pecas_pendentes(sa_conn)}
    assert {terno, camisa, sem_estoque} <= pendentes

    embeddings.gravar_embeddings(
        sa_conn, [(terno, _vetor(0)), (camisa, _vetor(1)), (sem_estoque, _vetor(0))]
    )
    pendentes = {p["id_produto"] for p in embeddings.pecas_pendentes(sa_conn)}
    assert not {terno, camisa, sem_estoque} & pendentes
    # Editar a peca depois do embedding a coloca de volta na fila.
    sa_conn.execute(
        text(
            "UPDATE produto SET atualizado_em = now() + interval '1 minute' WHERE id_produto = :p"
        ),
        {"p": camisa},
    )
    assert camisa in {p["id_produto"] for p in embeddings.pecas_pendentes(sa_conn)}

    # Pergunta "no eixo do terno": o terno vem primeiro; peca sem estoque nunca aparece.
    perto_do_terno = [0.0] * embeddings.DIMENSOES
    perto_do_terno[0], perto_do_terno[1] = 0.9, 0.1
    achadas = repositorio.buscar_produtos_semelhantes(
        sa_conn, embeddings.vetor_sql(perto_do_terno), 5, 2.0
    )
    # O banco guarda os nomes em minusculas (padronizacao do catalogo).
    nomes = [p["nome"].lower() for p in achadas]
    assert nomes[0].startswith("terno")
    assert not any(n.startswith("bermuda") for n in nomes)
    assert achadas[0]["distancia"] < achadas[1]["distancia"]
    assert achadas[0]["variacoes"][0]["tamanho"] == "M"


def test_gerar_em_lotes_sem_aplicar_nao_grava(sa_conn):
    peca = _peca(sa_conn, f"Cinto {uuid4().hex[:6]}")
    gerador = GeradorFalso()
    pecas = [p for p in embeddings.pecas_pendentes(sa_conn) if p["id_produto"] == peca]
    assert embeddings.gerar(sa_conn, gerador, pecas, aplicar=False) == 1
    assert gerador.textos and gerador.textos[0].lower().startswith("cinto")
    assert sa_conn.execute(
        text("SELECT embedding IS NULL FROM produto WHERE id_produto = :p"), {"p": peca}
    ).scalar_one()


class GeradorComLimite(GeradorFalso):
    """Recusa a primeira chamada com 429, como o plano gratuito do Gemini."""

    def __init__(self):
        super().__init__()
        self.recusou = False

    def documentos(self, textos):
        if not self.recusou:
            self.recusou = True
            raise embeddings.ErroEmbedding("HTTP 429", 429)
        return super().documentos(textos)


class SemCommit:
    """A conexao do teste, mas o commit de cada lote nao sai da transacao (desfeita no fim)."""

    def __init__(self, conexao):
        self._conexao = conexao
        self.commits = 0

    def commit(self):
        self.commits += 1

    def __getattr__(self, nome):
        return getattr(self._conexao, nome)


def test_gerar_em_lotes_pequenos_espera_o_limite_e_grava(sa_conn):
    ids = [_peca(sa_conn, f"Lote {i} {uuid4().hex[:6]}") for i in range(3)]
    pecas = [p for p in embeddings.pecas_pendentes(sa_conn) if p["id_produto"] in ids]
    esperas = []
    conexao = SemCommit(sa_conn)
    feitas = embeddings.gerar(
        conexao,
        GeradorComLimite(),
        pecas,
        aplicar=True,
        tamanho_do_lote=2,
        pausa=5,
        dormir=esperas.append,
    )
    assert conexao.commits == 2  # um commit por lote
    assert feitas == 3
    assert esperas == [60, 5]  # o limite do primeiro lote, depois a pausa antes do segundo
    gravadas = sa_conn.execute(
        text("SELECT count(*) FROM produto WHERE id_produto = ANY(:ids) AND embedding IS NOT NULL"),
        {"ids": ids},
    ).scalar_one()
    assert gravadas == 3
