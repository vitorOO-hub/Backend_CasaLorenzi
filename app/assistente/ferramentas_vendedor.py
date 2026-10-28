"""Ferramentas do assistente do vendedor: so leitura, sempre na loja do token.

Cada ferramenta embrulha um service que o vendedor ja usa nas telas (`app.vendas.service`) ou uma
leitura sem dado pessoal (lojas). O modelo escolhe a ferramenta e os argumentos de negocio; quem e o
vendedor e a loja dele vem do `UsuarioAtual`, que o servidor injeta. Nenhum argumento aceita loja,
usuario ou CPF de escopo, e os schemas recusam campo extra.

Saida enxuta: listas curtas, CPF mascarado (como nas telas) e sem e-mail nem telefone de cliente.
"""

import logging
import unicodedata
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Annotated, Any, get_args

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError
from sqlalchemy.engine import Connection

from app.assistente.provedores import Ferramenta
from app.cliente import repositorio as lojas_repositorio
from app.cliente.vencimento_pontos import SP
from app.core.erros import ErroDeNegocio
from app.core.erros_auth import SemPermissao
from app.core.horario import DIAS
from app.core.papeis import UsuarioAtual
from app.gerencia import repositorio as vendas_da_loja
from app.gerencia.repositorio import Filtro
from app.vendas import repositorio as vendas_repositorio
from app.vendas import service as vendas

registro = logging.getLogger("app.assistente")

MAX_DIAS_PERIODO = 92
LIMITE_LISTA = 10
LIMITE_PECAS = 15
CRITERIO_VENDAS = (
    "Pedidos pagos, separados ou entregues da sua loja, pela data do pedido, sem frete e sem "
    "cancelados."
)

Busca = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)]
TextoCurto = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=30)]


class _Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _hoje() -> date:
    return datetime.now(UTC).astimezone(SP).date()


def _dinheiro(valor: Any) -> float:
    return round(float(valor or 0), 2)


def _normal(texto: Any) -> str:
    texto = unicodedata.normalize("NFKD", str(texto or "").casefold())
    return "".join(c for c in texto if not unicodedata.combining(c)).strip()


def _loja_da_venda(conexao: Connection, usuario: UsuarioAtual):
    """Mesma regra das telas de venda: a loja que recebe as vendas da loja do token."""
    if usuario.id_loja is None:
        raise SemPermissao()
    return vendas_repositorio.loja_de_venda(conexao, usuario.id_loja)


# ------------------------------------------------------------------ vendas do periodo


class EntradaPeriodo(_Entrada):
    inicio: date | None = Field(default=None, description="Primeiro dia, formato AAAA-MM-DD")
    fim: date | None = Field(default=None, description="Ultimo dia, formato AAAA-MM-DD")


def vendas_do_periodo(conexao: Connection, usuario: UsuarioAtual, e: EntradaPeriodo) -> dict:
    hoje = _hoje()
    fim = e.fim or hoje
    inicio = e.inicio or fim
    if fim > hoje:
        return {"erro": "O periodo nao pode terminar depois de hoje."}
    if inicio > fim:
        return {"erro": "O inicio precisa ser antes do fim."}
    if (fim - inicio).days + 1 > MAX_DIAS_PERIODO:
        return {"erro": f"Consulte no maximo {MAX_DIAS_PERIODO} dias por vez."}
    id_loja = _loja_da_venda(conexao, usuario)
    filtro = Filtro(id_loja=id_loja)
    resumo = vendas_da_loja.resumo(conexao, filtro, inicio, fim)
    pedidos = int(resumo["pedidos"])
    faturamento = _dinheiro(resumo["faturamento"])
    mais_vendidas = vendas_da_loja.pecas_mais_vendidas(conexao, filtro, inicio, fim, limite=5)
    return {
        "loja": vendas_repositorio.nome_da_loja(conexao, id_loja),
        "inicio": inicio.isoformat(),
        "fim": fim.isoformat(),
        "criterio": CRITERIO_VENDAS,
        "faturamento": faturamento,
        "pedidos": pedidos,
        "pecas": int(resumo["pecas"]),
        "ticket_medio": round(faturamento / pedidos, 2) if pedidos else 0.0,
        "mais_vendidas": [
            {
                "produto": p["nome"],
                "unidades": int(p["unidades"]),
                "faturamento": _dinheiro(p["faturamento"]),
            }
            for p in mais_vendidas
        ],
    }


# ------------------------------------------------------------------ vendas e clientes


class EntradaBuscaVendas(_Entrada):
    busca: Busca | None = Field(
        default=None,
        description="Numero do pedido, nome ou CPF do cliente; vazio = as mais recentes",
    )
    limite: int = Field(default=5, ge=1, le=LIMITE_LISTA)


def buscar_vendas(conexao: Connection, usuario: UsuarioAtual, e: EntradaBuscaVendas) -> dict:
    lista = vendas.listar_vendas(conexao, usuario, e.busca, limit=e.limite, offset=0)
    return {
        "total": lista["total"],
        "vendas": [
            {
                "numero_pedido": v["numero_pedido"],
                "data": v["criado_em"].isoformat()
                if hasattr(v["criado_em"], "isoformat")
                else v["criado_em"],
                "cliente": v["cliente"],
                "vendedor": v["vendedor"],
                "status": v["status"],
                "canal": v["canal_venda"],
                "pecas": int(v["pecas"]),
                "valor_total": _dinheiro(v["valor_total"]),
            }
            for v in lista["itens"]
        ],
    }


class EntradaDetalheVenda(_Entrada):
    numero_pedido: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=2, max_length=40, pattern=r"^[A-Za-z0-9-]+$"
        ),
    ]


def detalhe_venda(conexao: Connection, usuario: UsuarioAtual, e: EntradaDetalheVenda) -> dict:
    achadas = vendas.listar_vendas(conexao, usuario, e.numero_pedido, limit=5, offset=0)["itens"]
    venda = next(
        (v for v in achadas if v["numero_pedido"].upper() == e.numero_pedido.upper()), None
    )
    if venda is None:
        return {"erro": "Nao encontrei esse pedido entre as vendas da sua loja."}
    detalhe = vendas.obter_venda(conexao, usuario, venda["id_pedido"])
    return {
        "numero_pedido": detalhe["numero_pedido"],
        "data": detalhe["criado_em"].isoformat(),
        "cliente": detalhe["cliente"],
        "vendedor": detalhe["vendedor"],
        "status": detalhe["status"],
        "metodo_pagamento": detalhe["metodo_pagamento"],
        "valor_total": _dinheiro(detalhe["valor_total"]),
        "itens": [
            {
                "sku": i["sku"],
                "produto": i["produto"],
                "cor": i["cor"],
                "tamanho": i["tamanho"],
                "quantidade": int(i["quantidade"]),
                "valor_total": _dinheiro(i["valor_total"])
                if i["valor_total"] is not None
                else None,
            }
            for i in detalhe["itens_da_venda"]
        ],
    }


class EntradaBuscaClientes(_Entrada):
    busca: Busca = Field(description="Nome, e-mail ou CPF do cliente")


def buscar_clientes(conexao: Connection, usuario: UsuarioAtual, e: EntradaBuscaClientes) -> dict:
    lista = vendas.listar_clientes(conexao, usuario, e.busca, limit=LIMITE_LISTA, offset=0)
    return {
        "total": lista["total"],
        "clientes": [
            {
                "nome": c["nome"],
                "cpf": c["cpf"],
                "cidade": c["cidade"],
                "cliente_desde": c["cliente_desde"].date().isoformat()
                if hasattr(c["cliente_desde"], "date")
                else c["cliente_desde"],
            }
            for c in lista["itens"]
        ],
    }


# ------------------------------------------------------------------ pecas, lojas e pagamento


class EntradaPecas(_Entrada):
    busca: Busca = Field(description="Nome da peca ou SKU, sem cor e tamanho (ex.: camisa linho)")
    cor: TextoCurto | None = Field(
        default=None, description="Cor, so se o vendedor disse qual (ex.: azul)"
    )
    tamanho: TextoCurto | None = Field(
        default=None, description="Tamanho, so se o vendedor disse qual (ex.: M, 42)"
    )


# Palavras que o vendedor fala mas que nao estao no nome da peca ("camisa DE linho").
_SEM_PESO = {"de", "da", "do", "das", "dos", "com", "sem", "para", "e", "a", "o", "em"}


def _pecas_por_palavras(conexao: Connection, usuario: UsuarioAtual, busca: str) -> list[dict]:
    """A busca das telas casa o texto inteiro (nome, SKU ou EAN). Sem resultado, procura pela
    palavra mais longa e exige que todas as palavras aparecam no nome ou no SKU."""
    pecas = vendas.pecas(conexao, usuario, busca, limit=50)
    palavras = [p for p in _normal(busca).split() if len(p) > 1 and p not in _SEM_PESO]
    if pecas or len(palavras) < 2:
        return pecas
    candidatas = vendas.pecas(conexao, usuario, max(palavras, key=len), limit=50)
    return [
        p
        for p in candidatas
        if all(palavra in _normal(f"{p['produto']} {p['sku']}") for palavra in palavras)
    ]


def consultar_pecas(conexao: Connection, usuario: UsuarioAtual, e: EntradaPecas) -> dict:
    pecas = _pecas_por_palavras(conexao, usuario, e.busca)
    if e.cor:
        pecas = [p for p in pecas if _normal(e.cor) in _normal(p["cor"])]
    if e.tamanho:
        pecas = [p for p in pecas if _normal(p["tamanho"]) == _normal(e.tamanho)]
    return {
        "observacao": "So pecas com saldo na sua loja.",
        "total": len(pecas),
        "pecas": [
            {
                "sku": p["sku"],
                "produto": p["produto"],
                "cor": p["cor"],
                "tamanho": p["tamanho"],
                "preco": _dinheiro(p["preco_venda"]),
                "disponivel": int(p["disponivel"]),
            }
            for p in pecas[:LIMITE_PECAS]
        ],
    }


class EntradaVazia(_Entrada):
    pass


def _horario_texto(horario: dict | None) -> str | None:
    if not horario:
        return None
    partes = []
    for dia in DIAS:
        turno = horario.get(dia)
        partes.append(f"{dia} {turno['abre']}-{turno['fecha']}" if turno else f"{dia} fechada")
    return ", ".join(partes)


def lojas_e_horarios(conexao: Connection, usuario: UsuarioAtual, e: EntradaVazia) -> dict:
    lojas = lojas_repositorio.listar_lojas(conexao)
    return {
        "lojas": [
            {
                "nome": loja["nome"],
                "cidade": loja["cidade"],
                "uf": loja["uf"],
                "endereco": loja["endereco"],
                "telefone": loja["telefone"],
                "horario": _horario_texto(loja["horario_funcionamento"])
                or "sem horario cadastrado",
            }
            for loja in lojas
            if loja["horario_funcionamento"] or loja["endereco"]
        ]
    }


def formas_de_pagamento(conexao: Connection, usuario: UsuarioAtual, e: EntradaVazia) -> dict:
    opcoes = vendas.opcoes(conexao, usuario)
    return {"loja": opcoes["loja"], "formas": [m["nome"] for m in opcoes["metodos"]]}


# ------------------------------------------------------------------ catalogo e execucao


Funcao = Callable[[Connection, UsuarioAtual, Any], dict]

_REGISTRO: dict[str, tuple[str, type[_Entrada], Funcao]] = {
    "vendas_do_periodo": (
        "Faturamento, numero de pedidos, pecas, ticket medio e pecas mais vendidas da loja do "
        "vendedor num periodo (padrao: hoje). Use para 'quanto vendemos hoje/na semana/no mes'.",
        EntradaPeriodo,
        vendas_do_periodo,
    ),
    "buscar_vendas": (
        "Lista as vendas da loja (mais recentes primeiro), opcionalmente filtrando por numero do "
        "pedido ou nome/CPF do cliente. Use para o historico de compras de um cliente na loja.",
        EntradaBuscaVendas,
        buscar_vendas,
    ),
    "detalhe_venda": (
        "Itens, pagamento e status de uma venda da loja pelo numero do pedido.",
        EntradaDetalheVenda,
        detalhe_venda,
    ),
    "buscar_clientes": (
        "Procura clientes da loja (cadastrados nela ou com compra nela) por nome, e-mail ou CPF.",
        EntradaBuscaClientes,
        buscar_clientes,
    ),
    "consultar_pecas": (
        "Pecas com saldo na loja do vendedor, com preco e quantidade disponivel. Filtre por cor e "
        "tamanho nos campos proprios.",
        EntradaPecas,
        consultar_pecas,
    ),
    "lojas_e_horarios": (
        "Endereco, telefone e horario de funcionamento das lojas da rede.",
        EntradaVazia,
        lojas_e_horarios,
    ),
    "formas_de_pagamento": (
        "Formas de pagamento aceitas na venda em loja.",
        EntradaVazia,
        formas_de_pagamento,
    ),
}


def _tipo_base(anotacao: Any) -> Any:
    """`int | None`, `Annotated[str, ...]` -> int, str (o tipo que o modelo precisa mandar)."""
    if isinstance(anotacao, type):
        return anotacao
    for argumento in get_args(anotacao):
        tipo = _tipo_base(argumento)
        if tipo is not None and tipo is not type(None):
            return tipo
    return None


def _parametros(modelo: type[_Entrada]) -> dict[str, Any]:
    """JSON Schema simples (tipos basicos) aceito pelos dois provedores."""
    propriedades: dict[str, Any] = {}
    obrigatorios = []
    for nome, campo in modelo.model_fields.items():
        tipo = _tipo_base(campo.annotation)
        propriedade: dict[str, Any] = {"type": "integer" if tipo is int else "string"}
        if campo.description:
            propriedade["description"] = campo.description
        propriedades[nome] = propriedade
        if campo.is_required():
            obrigatorios.append(nome)
    schema: dict[str, Any] = {"type": "object", "properties": propriedades}
    if obrigatorios:
        schema["required"] = obrigatorios
    return schema


FERRAMENTAS = [
    Ferramenta(nome, desc, _parametros(modelo)) for nome, (desc, modelo, _) in _REGISTRO.items()
]


def executar(
    conexao: Connection, usuario: UsuarioAtual, nome: str, argumentos: dict[str, Any]
) -> dict:
    """Valida e executa uma ferramenta da allowlist. Nunca levanta: erro vira `{"erro": ...}`."""
    item = _REGISTRO.get(nome)
    if item is None:
        return {"erro": "Ferramenta desconhecida."}
    _, modelo, funcao = item
    try:
        entrada = modelo.model_validate(argumentos)
    except ValidationError as erro:
        campos = sorted({".".join(str(p) for p in e["loc"]) or "argumentos" for e in erro.errors()})
        return {"erro": f"Argumentos invalidos: {', '.join(campos)}."}
    try:
        return funcao(conexao, usuario, entrada)
    except ErroDeNegocio as erro:
        return {"erro": erro.detalhe}
    except Exception:
        registro.exception("ferramenta %s falhou", nome)
        conexao.rollback()
        return {"erro": "Nao consegui consultar agora."}
