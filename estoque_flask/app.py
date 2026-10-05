"""Rotas Flask para exercitar as acoes da tabela estoque."""

from flask import Flask, jsonify, request
from psycopg import errors

from estoque_flask.config import carregar_configuracao
from estoque_flask.db import abrir_conexao
from estoque_flask.repositorio import (
    EstoqueComSaldo,
    EstoqueInsuficiente,
    RegistroNaoEncontrado,
    atualizar_estoque_minimo,
    criar_estoque,
    listar_estoques,
    normalizar_id,
    normalizar_quantidade,
    obter_estoque,
    registrar_entrada,
    registrar_saida,
    remover_estoque_sem_saldo,
)


def criar_app() -> Flask:
    app = Flask(__name__)
    configuracao = carregar_configuracao()

    def executar(operacao):
        with abrir_conexao(configuracao) as conexao:
            return operacao(conexao)

    @app.errorhandler(ValueError)
    def erro_validacao(erro: ValueError):
        return jsonify({"erro": str(erro)}), 422

    @app.errorhandler(RegistroNaoEncontrado)
    def erro_nao_encontrado(_erro: RegistroNaoEncontrado):
        return jsonify({"erro": "Estoque nao encontrado"}), 404

    @app.errorhandler(EstoqueInsuficiente)
    def erro_estoque_insuficiente(_erro: EstoqueInsuficiente):
        return jsonify({"erro": "Estoque insuficiente para realizar a saida"}), 409

    @app.errorhandler(EstoqueComSaldo)
    def erro_estoque_com_saldo(_erro: EstoqueComSaldo):
        return jsonify({"erro": "Nao e possivel remover estoque com saldo maior que zero"}), 409

    @app.errorhandler(errors.UniqueViolation)
    def erro_unico(_erro: errors.UniqueViolation):
        return jsonify({"erro": "Ja existe estoque para esta loja e variacao"}), 409

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/estoques")
    def listar():
        return jsonify(executar(listar_estoques))

    @app.get("/estoques/<id_estoque>")
    def obter(id_estoque: str):
        estoque_id = normalizar_id(id_estoque)
        return jsonify(executar(lambda conexao: obter_estoque(conexao, estoque_id)))

    @app.post("/estoques")
    def criar():
        dados = request.get_json(silent=True) or {}
        estoque = executar(
            lambda conexao: criar_estoque(
                conexao,
                id_loja=normalizar_id(dados["id_loja"]),
                id_variacao=normalizar_id(dados["id_variacao"]),
                quantidade=normalizar_quantidade(dados.get("quantidade", 0), permite_zero=True),
                estoque_minimo=normalizar_quantidade(
                    dados.get("estoque_minimo", 0),
                    nome="estoque_minimo",
                    permite_zero=True,
                ),
            )
        )
        return jsonify(estoque), 201

    @app.post("/estoques/<id_estoque>/entrada")
    def entrada(id_estoque: str):
        dados = request.get_json(silent=True) or {}
        estoque_id = normalizar_id(id_estoque)
        quantidade = normalizar_quantidade(dados["quantidade"])
        return jsonify(
            executar(
                lambda conexao: registrar_entrada(
                    conexao,
                    id_estoque=estoque_id,
                    quantidade=quantidade,
                )
            )
        )

    @app.post("/estoques/<id_estoque>/saida")
    def saida(id_estoque: str):
        dados = request.get_json(silent=True) or {}
        estoque_id = normalizar_id(id_estoque)
        quantidade = normalizar_quantidade(dados["quantidade"])
        return jsonify(
            executar(
                lambda conexao: registrar_saida(
                    conexao,
                    id_estoque=estoque_id,
                    quantidade=quantidade,
                )
            )
        )

    @app.patch("/estoques/<id_estoque>/minimo")
    def minimo(id_estoque: str):
        dados = request.get_json(silent=True) or {}
        estoque_id = normalizar_id(id_estoque)
        estoque_minimo = normalizar_quantidade(
            dados["estoque_minimo"],
            nome="estoque_minimo",
            permite_zero=True,
        )
        return jsonify(
            executar(
                lambda conexao: atualizar_estoque_minimo(
                    conexao,
                    id_estoque=estoque_id,
                    estoque_minimo=estoque_minimo,
                )
            )
        )

    @app.delete("/estoques/<id_estoque>")
    def remover(id_estoque: str):
        estoque_id = normalizar_id(id_estoque)
        estoque = executar(lambda conexao: remover_estoque_sem_saldo(conexao, id_estoque=estoque_id))
        return jsonify(estoque)

    return app


if __name__ == "__main__":
    criar_app().run(debug=True)
