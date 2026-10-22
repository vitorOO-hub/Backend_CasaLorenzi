"""Regras das vendas em loja: o vendedor ve as vendas e os clientes da loja dele e lanca venda.

Quem vende e a loja vem sempre do token. A venda baixa o estoque na mesma transacao: trava a linha
do estoque, confere o saldo e grava pedido, itens, pagamento e a movimentacao de venda. Qualquer
falha no meio desfaz tudo.

A loja da venda segue `loja_de_venda` (migration 20261022160000), a mesma regra do trigger de
`pedido`: assim o pedido e a baixa de estoque nunca caem em lojas diferentes.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from app.chamados.repositorio import id_usuario_ativo
from app.core.erros_auth import SemPermissao
from app.core.papeis import Papel, UsuarioAtual
from app.vendas import repositorio
from app.vendas.erros import (
    ClienteNaoEncontrado,
    EstoqueInsuficiente,
    LojaDaVendaInvalida,
    PecaIndisponivel,
    ReferenciaDeVendaInvalida,
    VendaNaoEncontrada,
    VendaNaoRegistrada,
)

PAPEIS_DE_VENDA = (Papel.VENDEDOR,)
CENTAVOS = Decimal("0.01")
OBSERVACAO_PADRAO = "Venda lancada em loja pelo vendedor."


def _cliente_publico(linha: dict[str, Any]) -> dict[str, Any]:
    return {**linha, "cpf": repositorio.mascarar_cpf(linha["cpf"])}


def _venda_publica(linha: dict[str, Any]) -> dict[str, Any]:
    publica = dict(linha)
    publica["cliente_cpf"] = repositorio.mascarar_cpf(linha.get("cliente_cpf"))
    return publica


def _lojas(conexao: Connection, usuario: UsuarioAtual) -> tuple[UUID, UUID]:
    """(loja do vendedor, loja que recebe as vendas dele). Em loja fisica as duas sao a mesma."""
    if usuario.id_loja is None:
        raise SemPermissao()
    return usuario.id_loja, repositorio.loja_de_venda(conexao, usuario.id_loja)


def _detalhe(conexao: Connection, id_loja: UUID, id_pedido: UUID) -> dict[str, Any]:
    venda = repositorio.venda_por_id(conexao, id_loja, id_pedido)
    if venda is None:
        raise VendaNaoEncontrada()
    return _venda_publica(venda)


# ------------------------------------------------------------------ leituras


def listar_clientes(
    conexao: Connection, usuario: UsuarioAtual, busca: str | None, *, limit: int, offset: int
) -> dict[str, Any]:
    """Os clientes da loja do vendedor (cadastrados nela ou com compra nela)."""
    id_loja, id_loja_venda = _lojas(conexao, usuario)
    total, itens = repositorio.listar_clientes(
        conexao, id_loja, id_loja_venda, busca, limit=limit, offset=offset
    )
    return {"total": total, "itens": [_cliente_publico(i) for i in itens]}


def buscar_cliente(conexao: Connection, cpf: str) -> dict[str, Any]:
    """Achar pelo CPF vale para qualquer cliente cadastrado: quem compra pode ser de outra loja."""
    cliente = repositorio.cliente_por_cpf(conexao, cpf)
    if cliente is None:
        raise ClienteNaoEncontrado()
    return _cliente_publico(cliente)


def listar_vendas(
    conexao: Connection, usuario: UsuarioAtual, busca: str | None, *, limit: int, offset: int
) -> dict[str, Any]:
    """So as vendas da loja do vendedor."""
    _, id_loja = _lojas(conexao, usuario)
    total, itens = repositorio.listar_vendas(conexao, id_loja, busca, limit=limit, offset=offset)
    return {"total": total, "itens": [_venda_publica(i) for i in itens]}


def obter_venda(conexao: Connection, usuario: UsuarioAtual, id_pedido: UUID) -> dict[str, Any]:
    """Venda de outra loja responde como se nao existisse (404)."""
    _, id_loja = _lojas(conexao, usuario)
    return _detalhe(conexao, id_loja, id_pedido)


def opcoes(conexao: Connection, usuario: UsuarioAtual) -> dict[str, Any]:
    loja = None
    if usuario.id_loja is not None:
        _, id_loja = _lojas(conexao, usuario)
        loja = repositorio.nome_da_loja(conexao, id_loja)
    return {"metodos": repositorio.metodos(conexao), "loja": loja}


def pecas(
    conexao: Connection, usuario: UsuarioAtual, busca: str | None, *, limit: int
) -> list[dict[str, Any]]:
    _, id_loja = _lojas(conexao, usuario)
    return repositorio.pecas_da_loja(conexao, id_loja, busca, limit=limit)


# --------------------------------------------------------------------- venda


def _juntar_itens(itens: list[dict[str, Any]]) -> list[tuple[UUID, int]]:
    """Mesma peca repetida vira uma linha; ordem fixa evita travas cruzadas entre vendas."""
    somadas: dict[UUID, int] = {}
    for item in itens:
        somadas[item["id_variacao"]] = somadas.get(item["id_variacao"], 0) + item["quantidade"]
    return sorted(somadas.items(), key=lambda par: str(par[0]))


def _observacao(texto: str | None) -> str:
    texto = (texto or "").strip()
    return f"{OBSERVACAO_PADRAO} Obs: {texto}" if texto else OBSERVACAO_PADRAO


def lancar_venda(
    conexao: Connection,
    usuario: UsuarioAtual,
    dados: dict[str, Any],
    *,
    chave_idempotencia: str | None = None,
) -> dict[str, Any]:
    id_vendedor = id_usuario_ativo(conexao, usuario.id_auth)
    if id_vendedor is None:
        raise SemPermissao()
    chave = f"venda-loja-{chave_idempotencia}" if chave_idempotencia else None

    try:
        _, id_loja = _lojas(conexao, usuario)
        if chave:
            repositorio.travar_chave(conexao, chave)
            repetida = repositorio.venda_da_chave(conexao, id_vendedor, chave)
            if repetida:
                conexao.rollback()
                return _detalhe(conexao, id_loja, repetida)
        if repositorio.nome_da_loja(conexao, id_loja) is None:
            raise LojaDaVendaInvalida()
        cliente = repositorio.cliente_por_cpf(conexao, dados["cpf"])
        if cliente is None:
            raise ClienteNaoEncontrado()
        id_status = repositorio.id_de_apoio(conexao, "status_pedido", "entregue")
        id_metodo = repositorio.id_de_apoio(conexao, "metodo_pagamento", dados["metodo_pagamento"])
        id_pago = repositorio.id_de_apoio(conexao, "status_pagamento", "aprovado")
        id_tipo = repositorio.id_de_apoio(conexao, "tipo_movimentacao_estoque", "venda")
        if id_status is None or id_metodo is None or id_pago is None or id_tipo is None:
            raise ReferenciaDeVendaInvalida()

        linhas = []
        total = Decimal("0.00")
        for id_variacao, quantidade in _juntar_itens(dados["itens"]):
            peca = repositorio.travar_peca(conexao, id_loja, id_variacao)
            if peca is None:
                raise PecaIndisponivel()
            if int(peca["quantidade"]) < quantidade:
                raise EstoqueInsuficiente(str(peca["sku"]), int(peca["quantidade"]))
            preco = Decimal(peca["preco_venda"]).quantize(CENTAVOS)
            linhas.append((id_variacao, quantidade, int(peca["quantidade"]), preco))
            total += preco * quantidade

        total = total.quantize(CENTAVOS)
        numero = f"PD-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:8].upper()}"
        id_pedido = repositorio.inserir_pedido(
            conexao,
            (
                numero,
                id_loja,
                cliente["id_cliente"],
                id_vendedor,
                id_status,
                total,
                _observacao(dados.get("observacao")),
            ),
        )
        for id_variacao, quantidade, anterior, preco in linhas:
            repositorio.baixar_item(
                conexao,
                id_pedido=id_pedido,
                id_loja=id_loja,
                id_variacao=id_variacao,
                id_vendedor=id_vendedor,
                id_tipo_venda=id_tipo,
                quantidade=quantidade,
                anterior=anterior,
                preco=preco,
                numero=numero,
            )
        repositorio.inserir_pagamento(
            conexao,
            id_pedido=id_pedido,
            id_metodo=id_metodo,
            id_status=id_pago,
            valor=total,
            chave=chave or f"venda-loja-{numero}",
        )
        conexao.commit()
    except IntegrityError as erro:
        conexao.rollback()
        raise VendaNaoRegistrada() from erro
    except Exception:
        conexao.rollback()
        raise
    return _detalhe(conexao, id_loja, id_pedido)
