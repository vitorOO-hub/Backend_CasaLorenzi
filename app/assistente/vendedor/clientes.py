"""Consultas de cliente do assistente do vendedor: achar o cliente e o que ele comprou num dia.

Escopo e visibilidade sao os da tela Clientes do vendedor (`app.vendas`): o mesmo trecho de SQL
(`_DA_LOJA`, `_CLIENTES`) e a mesma mascara de CPF (`mascarar_cpf`, so os dois ultimos digitos). O
que muda e so a busca, que aqui ignora acento e caixa no nome. Compras: so pedidos da loja que
recebe as vendas do vendedor, com o mesmo criterio de venda do painel (pago, separado, entregue).

Cliente de outra loja e cliente que nao existe dao a mesma resposta (`NAO_ENCONTREI`), para nao
revelar quem existe fora do acesso do vendedor. Somas e totais sao feitos aqui, no SQL.
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.engine import Connection

from app.assistente.vendedor.datas import Periodo, dia
from app.assistente.vendedor.estoque import _sem_acento
from app.core.erros_auth import SemPermissao
from app.core.papeis import UsuarioAtual
from app.core.repositorio import buscar_todos, buscar_um
from app.gerencia.repositorio import STATUS_DE_VENDA
from app.vendas import repositorio as vendas_repositorio
from app.vendas.repositorio import _CLIENTES, _DA_LOJA, mascarar_cpf
from app.vendas.schemas import so_digitos

NAO_ENCONTREI = "Não encontrei cliente com esse dado no seu acesso."
MUITOS = (
    "Encontrei mais de {n} clientes com esse nome. Me passe o e-mail ou o CPF do cliente para eu "
    "achar o certo."
)
ESCOLHER = "Qual deles? Responda com o número da lista ou com o CPF."
CRITERIO_COMPRAS = "Pedidos pagos, separados ou entregues na sua loja (sem cancelados)."
LIMITE_HOMONIMOS = 5
LIMITE_PEDIDOS = 5
LIMITE_ITENS = 10

Campo = Literal["cpf", "email", "telefone", "cidade", "cliente_desde"]
# Chaves curtas no resultado (menos tokens); `nome` vai sempre.
CHAVE_CURTA = {
    "cpf": "cpf",
    "email": "email",
    "telefone": "tel",
    "cidade": "cidade",
    "cliente_desde": "desde",
}
ROTULO = {
    "cpf": "CPF",
    "email": "e-mail",
    "telefone": "telefone",
    "cidade": "cidade",
    "cliente_desde": "cliente desde",
}


def _normal(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.casefold())
    return " ".join("".join(c for c in texto if not unicodedata.combining(c)).split())


@dataclass(frozen=True)
class Busca:
    """Busca validada: CPF ou telefone (so digitos), e-mail (minusculo) ou palavras do nome."""

    tipo: Literal["documento", "email", "nome"]
    valor: str
    palavras: tuple[str, ...] = ()


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_CPF = re.compile(r"(?<!\d)\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?!\d)")


def interpretar(busca: str) -> Busca | None:
    texto = (busca or "").strip()
    if achado := _EMAIL.search(texto):
        return Busca("email", achado.group().casefold())
    digitos = so_digitos(texto)
    if not re.search(r"[^\W\d_]", texto):
        # So numeros e pontuacao: CPF (11) ou telefone com DDD (10 ou 11), como na tela.
        return Busca("documento", digitos) if len(digitos) in (10, 11) else None
    palavras = tuple(p for p in re.findall(r"[a-z0-9]+", _normal(texto)) if len(p) > 1)
    return Busca("nome", " ".join(palavras), palavras) if palavras else None


def busca_na_pergunta(pergunta: str) -> Busca | None:
    """CPF ou e-mail completos escritos na pergunta: o backend acha o cliente sem o modelo."""
    if achado := _EMAIL.search(pergunta):
        return Busca("email", achado.group().casefold())
    if achado := _CPF.search(pergunta):
        return Busca("documento", so_digitos(achado.group()))
    return None


def _lojas(conexao: Connection, usuario: UsuarioAtual) -> tuple[UUID, UUID]:
    """(loja do vendedor, loja que recebe as vendas dele), como em `app.vendas.service`."""
    if usuario.id_loja is None:
        raise SemPermissao()
    return usuario.id_loja, vendas_repositorio.loja_de_venda(conexao, usuario.id_loja)


def _condicao(busca: Busca | UUID) -> tuple[str, tuple[Any, ...]]:
    if isinstance(busca, UUID):
        return "u.id_usuario = %s", (busca,)
    if busca.tipo == "email":
        return "lower(u.email) = %s", (busca.valor,)
    if busca.tipo == "documento":
        return (
            "(u.documento = %s "
            "OR regexp_replace(COALESCE(u.telefone, ''), '[^0-9]', '', 'g') = %s)",
            (busca.valor, busca.valor),
        )
    nome = _sem_acento("u.nome")
    return (
        " AND ".join(f"{nome} LIKE %s" for _ in busca.palavras),
        tuple(f"%{p}%" for p in busca.palavras),
    )


def procurar(
    conexao: Connection, usuario: UsuarioAtual, busca: Busca | UUID, limite: int
) -> list[dict[str, Any]]:
    """Clientes da loja do vendedor que casam com a busca (no maximo `limite`)."""
    id_loja, id_loja_venda = _lojas(conexao, usuario)
    condicao, parametros = _condicao(busca)
    base = _CLIENTES.format(filtro=f"{_DA_LOJA} AND {condicao}")
    return buscar_todos(
        conexao,
        f"""
        SELECT u.id_usuario AS id_cliente, u.nome, u.documento AS cpf, u.email, u.telefone,
               u.cidade, u.criado_em AS cliente_desde,
               (SELECT max(p.criado_em) FROM pedido p
                 WHERE p.id_cliente = u.id_usuario AND p.id_loja = %s) AS ultima_compra
        {base}
        ORDER BY u.nome, u.id_usuario
        LIMIT %s
        """,  # nosec B608 - filtro montado so com constantes; valores por parametro
        (id_loja_venda, id_loja, id_loja_venda, *parametros, limite),
    )


def _data(valor: Any) -> str | None:
    if valor is None:
        return None
    return dia(valor.date() if hasattr(valor, "date") else valor)


def _valor(linha: dict[str, Any], campo: str) -> Any:
    if campo == "cpf":
        return mascarar_cpf(linha["cpf"]) if linha.get("cpf") else None
    if campo == "cliente_desde":
        return _data(linha.get("cliente_desde"))
    return linha.get(campo) or None


def resultado_da_busca(linhas: list[dict[str, Any]], campos: list[str]) -> dict[str, Any]:
    """Saida compacta: so os campos pedidos, chaves curtas e sem nulos."""
    if not linhas:
        return {"nao_encontrado": NAO_ENCONTREI}
    if len(linhas) > LIMITE_HOMONIMOS:
        return {"muitos": MUITOS.format(n=LIMITE_HOMONIMOS)}
    if len(linhas) > 1:
        return {
            "opcoes": [
                {
                    # O id fica no backend (pendencia da conversa) e sai antes de ir ao modelo.
                    "_id": str(linha["id_cliente"]),
                    "n": n,
                    "nome": linha["nome"],
                    "cpf": mascarar_cpf(linha["cpf"]),
                    "ultima_compra": _data(linha.get("ultima_compra")) or "sem compras na loja",
                }
                for n, linha in enumerate(linhas, start=1)
            ],
            "pergunta": ESCOLHER,
        }
    linha = linhas[0]
    saida: dict[str, Any] = {"cliente_id": str(linha["id_cliente"]), "nome": linha["nome"]}
    faltam = []
    for campo in dict.fromkeys(campos):
        valor = _valor(linha, campo)
        if valor is None:
            faltam.append(ROTULO[campo])
        else:
            saida[CHAVE_CURTA[campo]] = valor
    if faltam:
        saida["sem_cadastro"] = faltam
    return saida


# ------------------------------------------------------------------ compras


def compras(
    conexao: Connection, usuario: UsuarioAtual, id_cliente: UUID, periodo: Periodo
) -> dict[str, Any] | None:
    """Pedidos do cliente na loja do vendedor no periodo, com itens e totais somados no SQL.
    `None` se o cliente nao esta no acesso do vendedor."""
    achados = procurar(conexao, usuario, id_cliente, 1)
    if not achados:
        return None
    _, id_loja = _lojas(conexao, usuario)
    filtro = (
        "FROM pedido p JOIN status_pedido s ON s.id_status_pedido = p.id_status_pedido "
        "WHERE p.id_loja = %s AND p.id_cliente = %s AND s.codigo = ANY(%s) "
        "AND p.criado_em >= (%s::date)::timestamp AT TIME ZONE 'America/Sao_Paulo' "
        "AND p.criado_em < (%s::date + 1)::timestamp AT TIME ZONE 'America/Sao_Paulo'"
    )
    parametros = (id_loja, id_cliente, list(STATUS_DE_VENDA), periodo.inicio, periodo.fim)
    totais = buscar_um(
        conexao,
        f"""
        SELECT count(*)::int AS pedidos, COALESCE(sum(p.valor_total), 0) AS total,
               COALESCE(sum((SELECT sum(ip.quantidade) FROM item_pedido ip
                              WHERE ip.id_pedido = p.id_pedido)), 0)::int AS itens
        {filtro}
        """,  # nosec B608
        parametros,
    ) or {"pedidos": 0, "total": 0, "itens": 0}
    pedidos = buscar_todos(
        conexao,
        f"SELECT p.id_pedido, p.numero_pedido, p.criado_em, p.valor_total {filtro} "  # nosec B608
        "ORDER BY p.criado_em, p.id_pedido LIMIT %s",
        (*parametros, LIMITE_PEDIDOS),
    )
    itens = (
        buscar_todos(
            conexao,
            """
        SELECT ip.id_pedido, pr.nome AS produto, va.cor, va.tamanho, ip.quantidade,
               ip.preco_unitario
        FROM item_pedido ip
        JOIN variacao_produto va ON va.id_variacao = ip.id_variacao
        JOIN produto pr ON pr.id_produto = va.id_produto
        WHERE ip.id_pedido = ANY(%s)
        ORDER BY pr.nome, va.cor, va.tamanho
        """,
            ([p["id_pedido"] for p in pedidos],),
        )
        if pedidos
        else []
    )
    return montar_compras(achados[0]["nome"], periodo, totais, pedidos, itens)


def _dinheiro(valor: Any) -> float:
    return round(float(valor or 0), 2)


def montar_compras(
    nome: str,
    periodo: Periodo,
    totais: dict[str, Any],
    pedidos: list[dict[str, Any]],
    itens: list[dict[str, Any]],
) -> dict[str, Any]:
    saida: dict[str, Any] = {"cliente": nome, "periodo": periodo.rotulo}
    if periodo.aviso:
        saida["aviso"] = periodo.aviso
    if not totais["pedidos"]:
        saida["sem_compras"] = f"sem compras em {periodo.rotulo}"
        return saida
    truncado = totais["pedidos"] > len(pedidos)
    lista = []
    for p in pedidos:
        do_pedido = [i for i in itens if i["id_pedido"] == p["id_pedido"]]
        truncado = truncado or len(do_pedido) > LIMITE_ITENS
        pedido: dict[str, Any] = {
            "numero": p["numero_pedido"],
            "itens": [
                {
                    "produto": " ".join(
                        str(x) for x in (i["produto"], i["cor"], i["tamanho"]) if x
                    ),
                    "qtd": int(i["quantidade"]),
                    "unit": _dinheiro(i["preco_unitario"]),
                }
                for i in do_pedido[:LIMITE_ITENS]
            ],
            "total": _dinheiro(p["valor_total"]),
        }
        if periodo.inicio != periodo.fim:
            pedido["data"] = _data(p["criado_em"])
        lista.append(pedido)
    saida |= {
        "criterio": CRITERIO_COMPRAS,
        "pedidos": lista,
        "qtd_pedidos": int(totais["pedidos"]),
        "qtd_itens": int(totais["itens"]),
        "total": _dinheiro(totais["total"]),
        "truncado": truncado,
    }
    return saida


def hoje_valido(periodo: Periodo, hoje: date) -> str | None:
    if periodo.inicio > hoje:
        return f"A data {dia(periodo.inicio)} ainda não chegou."
    return None
