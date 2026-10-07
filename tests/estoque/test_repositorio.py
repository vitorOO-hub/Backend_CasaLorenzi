from datetime import datetime, timezone

import pytest

from app.estoque.erros import EstoqueComSaldo, EstoqueInsuficiente, RegistroNaoEncontrado
from app.estoque.repositorio import (
    normalizar_id,
    normalizar_quantidade,
    registrar_entrada,
    registrar_saida,
    remover_estoque_sem_saldo,
)


class ResultadoFalso:
    def __init__(self, resultado):
        self.resultado = resultado

    def mappings(self):
        return self

    def first(self):
        return self.resultado

    def all(self):
        if self.resultado is None:
            return []
        if isinstance(self.resultado, list):
            return self.resultado
        return [self.resultado]


class ConexaoFalsa:
    def __init__(self, linhas):
        self.linhas = linhas
        self.sqls = []
        self.parametros = []
        self.commits = 0
        self.rollbacks = 0

    def exec_driver_sql(self, sql, parametros=()):
        return ResultadoFalso(self.executar_sql_falso(sql, parametros))

    def executar_sql_falso(self, sql, parametros=()):
        self.sqls.append(sql)
        self.parametros.append(parametros)
        sql_normalizado = " ".join(sql.split()).upper()

        if sql_normalizado.startswith("UPDATE ESTOQUE SET QUANTIDADE = QUANTIDADE +"):
            quantidade, id_estoque = parametros
            linha_atual = self.linhas.get(id_estoque)
            if linha_atual:
                linha_nova = {**linha_atual, "quantidade": linha_atual["quantidade"] + quantidade}
                self.linhas[id_estoque] = linha_nova
                return linha_nova
            return None

        if sql_normalizado.startswith("UPDATE ESTOQUE SET QUANTIDADE = QUANTIDADE -"):
            quantidade, id_estoque, minimo = parametros
            linha_atual = self.linhas.get(id_estoque)
            if linha_atual and linha_atual["quantidade"] >= minimo:
                linha_nova = {**linha_atual, "quantidade": linha_atual["quantidade"] - quantidade}
                self.linhas[id_estoque] = linha_nova
                return linha_nova
            return None

        if sql_normalizado.startswith("SELECT * FROM ESTOQUE WHERE ID_ESTOQUE"):
            return self.linhas.get(parametros[0])

        if sql_normalizado.startswith("DELETE FROM ESTOQUE"):
            id_estoque = parametros[0]
            linha_atual = self.linhas.get(id_estoque)
            if linha_atual and linha_atual["quantidade"] == 0:
                return self.linhas.pop(id_estoque)
            return None

        raise AssertionError(f"SQL inesperado: {sql}")

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def linha(quantidade):
    return {
        "id_estoque": 1,
        "id_loja": 1,
        "id_variacao": 1,
        "quantidade": quantidade,
        "estoque_minimo": 2,
        "atualizado_em": datetime(2026, 10, 5, tzinfo=timezone.utc),
    }


def test_normaliza_ids_bigint_e_uuid():
    assert normalizar_id("123") == 123
    assert str(normalizar_id("11111111-1111-1111-1111-111111111111")) == (
        "11111111-1111-1111-1111-111111111111"
    )


def test_quantidade_precisa_ser_positiva_por_padrao():
    with pytest.raises(ValueError):
        normalizar_quantidade(0)


def test_quantidade_pode_ser_zero_quando_permitido():
    assert normalizar_quantidade(0, permite_zero=True) == 0


def test_registrar_entrada_incrementa_saldo_e_commita():
    conexao = ConexaoFalsa({1: linha(5)})
    atualizado = registrar_entrada(conexao, id_estoque=1, quantidade=3)
    assert atualizado["quantidade"] == 8
    assert conexao.commits == 1
    assert conexao.rollbacks == 0


def test_registrar_saida_usa_update_atomico_para_impedir_estoque_negativo():
    conexao = ConexaoFalsa({1: linha(5)})
    atualizado = registrar_saida(conexao, id_estoque=1, quantidade=4)
    assert atualizado["quantidade"] == 1
    assert "AND quantidade >= %s" in conexao.sqls[0]
    assert conexao.parametros[0] == (4, 1, 4)
    assert conexao.commits == 1


def test_registrar_saida_falha_quando_saldo_e_insuficiente():
    conexao = ConexaoFalsa({1: linha(2)})
    with pytest.raises(EstoqueInsuficiente):
        registrar_saida(conexao, id_estoque=1, quantidade=3)
    assert conexao.rollbacks == 1


def test_registrar_saida_falha_quando_registro_nao_existe():
    conexao = ConexaoFalsa({})
    with pytest.raises(RegistroNaoEncontrado):
        registrar_saida(conexao, id_estoque=999, quantidade=1)
    assert conexao.rollbacks == 1


def test_remove_apenas_estoque_sem_saldo():
    conexao = ConexaoFalsa({1: linha(0)})
    removido = remover_estoque_sem_saldo(conexao, id_estoque=1)
    assert removido["id_estoque"] == 1
    assert conexao.linhas == {}
    assert conexao.commits == 1


def test_nao_remove_estoque_com_saldo():
    conexao = ConexaoFalsa({1: linha(1)})
    with pytest.raises(EstoqueComSaldo):
        remover_estoque_sem_saldo(conexao, id_estoque=1)
    assert conexao.rollbacks == 1
