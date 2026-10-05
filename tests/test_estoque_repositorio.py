from datetime import datetime, timezone

import pytest

from estoque_flask.repositorio import (
    EstoqueComSaldo,
    EstoqueInsuficiente,
    RegistroNaoEncontrado,
    normalizar_id,
    normalizar_quantidade,
    registrar_entrada,
    registrar_saida,
    remover_estoque_sem_saldo,
)


class CursorFalso:
    def __init__(self, conexao):
        self.conexao = conexao
        self.resultado = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, parametros=()):
        self.conexao.sqls.append(sql)
        self.conexao.parametros.append(parametros)
        sql_normalizado = " ".join(sql.split()).upper()

        if sql_normalizado.startswith("UPDATE ESTOQUE SET QUANTIDADE = QUANTIDADE +"):
            quantidade, id_estoque = parametros
            linha_atual = self.conexao.linhas.get(id_estoque)
            if linha_atual:
                linha_nova = {**linha_atual, "quantidade": linha_atual["quantidade"] + quantidade}
                self.conexao.linhas[id_estoque] = linha_nova
                self.resultado = linha_nova
            else:
                self.resultado = None
            return

        if sql_normalizado.startswith("UPDATE ESTOQUE SET QUANTIDADE = QUANTIDADE -"):
            quantidade, id_estoque, minimo = parametros
            linha_atual = self.conexao.linhas.get(id_estoque)
            if linha_atual and linha_atual["quantidade"] >= minimo:
                linha_nova = {**linha_atual, "quantidade": linha_atual["quantidade"] - quantidade}
                self.conexao.linhas[id_estoque] = linha_nova
                self.resultado = linha_nova
            else:
                self.resultado = None
            return

        if sql_normalizado.startswith("SELECT * FROM ESTOQUE WHERE ID_ESTOQUE"):
            self.resultado = self.conexao.linhas.get(parametros[0])
            return

        if sql_normalizado.startswith("DELETE FROM ESTOQUE"):
            id_estoque = parametros[0]
            linha_atual = self.conexao.linhas.get(id_estoque)
            if linha_atual and linha_atual["quantidade"] == 0:
                self.resultado = self.conexao.linhas.pop(id_estoque)
            else:
                self.resultado = None
            return

        raise AssertionError(f"SQL inesperado: {sql}")

    def fetchone(self):
        return self.resultado


class ConexaoFalsa:
    def __init__(self, linhas):
        self.linhas = linhas
        self.sqls = []
        self.parametros = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return CursorFalso(self)

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
