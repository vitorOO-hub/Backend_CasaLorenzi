from uuid import uuid4

from app.gerencia import repositorio
from app.gerencia.repositorio import Filtro


class ResultadoVetorial:
    def __init__(self, valores):
        self.valores = valores

    def scalars(self):
        return iter(self.valores)


class ConexaoVetorial:
    def __init__(self, valores):
        self.valores = valores
        self.consultas = []

    def execute(self, consulta, parametros):
        self.consultas.append((str(consulta), parametros))
        return ResultadoVetorial(self.valores)


def test_busca_semantica_de_produto_e_limitada_a_loja_e_categoria():
    loja = uuid4()
    ids = [uuid4(), uuid4()]
    conexao = ConexaoVetorial(ids)

    resultado = repositorio.produtos_semanticos_da_unidade(
        conexao, loja, "[0.1,0.2]", categoria="camisas", limite=10
    )

    sql, parametros = conexao.consultas[0]
    assert resultado == ids
    assert "e.id_loja = CAST(:id_loja AS uuid)" in sql
    assert "produto.embedding OPERATOR(extensions.<=>)" in sql
    assert parametros == {
        "id_loja": str(loja),
        "categoria": "camisas",
        "embedding": "[0.1,0.2]",
        "limite": 10,
    }


def test_busca_literal_consulta_apenas_produtos_com_estoque_na_loja():
    loja = uuid4()
    ids = [uuid4()]
    conexao = ConexaoVetorial(ids)

    resultado = repositorio.produtos_da_unidade_por_texto(
        conexao, loja, "camisa de linho", categoria="camisas"
    )

    sql, parametros = conexao.consultas[0]
    assert resultado == ids
    assert "e.id_loja = CAST(:id_loja AS uuid)" in sql
    assert "produto.cores::text" in sql
    assert parametros["id_loja"] == str(loja)
    assert parametros["busca"] == "camisa de linho"
    assert parametros["categoria"] == "camisas"


def test_consultas_de_estoque_aplicam_ids_semanticos_de_produto():
    loja = uuid4()
    produtos = (uuid4(), uuid4())

    class ResultadoConsulta:
        def scalar_one(self):
            return 0

        def mappings(self):
            return []

    class ConexaoConsulta:
        def __init__(self):
            self.consultas = []

        def execute(self, consulta, parametros):
            self.consultas.append((str(consulta), parametros))
            return ResultadoConsulta()

    conexao = ConexaoConsulta()
    filtro = Filtro(id_loja=loja)
    repositorio.reposicao(conexao, filtro, limite=20, ids_produto=produtos)
    repositorio.estoque_parado(
        conexao, filtro, dias=60, limite=30, ids_produto=produtos
    )

    assert len(conexao.consultas) == 3
    for sql, parametros in conexao.consultas:
        assert "ANY(CAST(:ids_produto AS uuid[]))" in sql
        assert parametros["ids_produto"] == [str(id_produto) for id_produto in produtos]
        assert parametros["id_loja"] == str(loja)
