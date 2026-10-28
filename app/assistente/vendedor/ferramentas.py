"""Ferramentas do assistente do vendedor: so leitura, sempre na loja do token.

Cada ferramenta embrulha um service que o vendedor ja usa nas telas (`app.vendas.service`) ou uma
leitura sem dado pessoal (lojas). O modelo escolhe a ferramenta e os argumentos de negocio; quem e o
vendedor e a loja dele vem do `UsuarioAtual`, que o servidor injeta. Nenhum argumento aceita loja,
usuario ou CPF de escopo, e os schemas recusam campo extra.

Saida enxuta: listas curtas, CPF mascarado (como nas telas) e sem e-mail nem telefone de cliente.
"""

import logging
import re
import unicodedata
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, Literal, get_args, get_origin
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError
from sqlalchemy.engine import Connection

from app.assistente.vendedor import clientes, datas
from app.assistente.vendedor import estoque as estoque_vendedor
from app.assistente.vendedor.provedores import Ferramenta
from app.cliente import repositorio as lojas_repositorio
from app.cliente.vencimento_pontos import SP
from app.core.erros import ErroDeNegocio
from app.core.erros_auth import SemPermissao
from app.core.horario import DIAS
from app.core.papeis import UsuarioAtual
from app.gerencia import repositorio as vendas_da_loja
from app.gerencia.repositorio import STATUS_DE_VENDA, Filtro
from app.painel_estoque import repositorio as estoque_repositorio
from app.painel_estoque import service as estoque
from app.painel_estoque.repositorio import FiltroSaldo
from app.vendas import repositorio as vendas_repositorio
from app.vendas import service as vendas

registro = logging.getLogger("app.assistente")

MAX_DIAS_PERIODO = 92
# Ranking de clientes: padrao dos ultimos 90 dias, ate um ano.
DIAS_DO_RANKING = 90
MAX_DIAS_RANKING = 366
LIMITE_LISTA = 10
LIMITE_PECAS = 15
CRITERIO_VENDAS = (
    "Pedidos pagos, separados ou entregues da sua loja, pela data do pedido, sem frete e sem "
    "cancelados."
)

Busca = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)]
TextoCurto = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=30)]
TextoData = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=40)]


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
    inicio: date | None = Field(
        default=None,
        description="Primeiro dia, AAAA-MM-DD; vazio se o vendedor nao disse o periodo",
    )
    fim: date | None = Field(
        default=None, description="Ultimo dia, AAAA-MM-DD; vazio se o vendedor nao disse o periodo"
    )


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
                "posicao": posicao,
                "produto": p["nome"],
                "unidades": int(p["unidades"]),
                "faturamento": _dinheiro(p["faturamento"]),
            }
            for posicao, p in enumerate(mais_vendidas, start=1)
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
                # Sem CPF, e-mail e telefone: o chat mostra so o nome (a tela Clientes tem o resto).
                "nome": c["nome"],
                "cidade": c["cidade"],
                "cliente_desde": c["cliente_desde"].date().isoformat()
                if hasattr(c["cliente_desde"], "date")
                else c["cliente_desde"],
            }
            for c in lista["itens"]
        ],
    }


class EntradaBuscarCliente(_Entrada):
    busca: Busca = Field(description="Nome, e-mail ou CPF do cliente, como o vendedor escreveu")
    campos: list[clientes.Campo] = Field(
        default_factory=list, max_length=5, description="Dados pedidos pelo vendedor"
    )


def buscar_cliente(conexao: Connection, usuario: UsuarioAtual, e: EntradaBuscarCliente) -> dict:
    """Um cliente da loja do vendedor, so com os campos pedidos (CPF mascarado, como na tela)."""
    busca = clientes.interpretar(e.busca)
    if busca is None:
        return {"nao_encontrado": clientes.NAO_ENCONTREI}
    linhas = clientes.procurar(conexao, usuario, busca, clientes.LIMITE_HOMONIMOS + 1)
    return clientes.resultado_da_busca(linhas, e.campos)


class EntradaCompras(_Entrada):
    cliente_id: UUID = Field(description="cliente_id devolvido por buscar_cliente")
    data: TextoData = Field(
        description="Dia ou periodo como o vendedor falou (ex.: ontem, dia 15, 15/10, outubro)"
    )


def compras_do_cliente(conexao: Connection, usuario: UsuarioAtual, e: EntradaCompras) -> dict:
    """Pedidos do cliente na loja do vendedor num dia ou periodo; a data e resolvida aqui."""
    hoje = _hoje()
    periodo = datas.resolver(e.data, hoje)
    if periodo is None:
        return {"erro": "Não entendi a data. Diga o dia, por exemplo: ontem, 15/10 ou 15/10/2026."}
    if erro := clientes.hoje_valido(periodo, hoje):
        return {"erro": erro}
    if (periodo.fim - periodo.inicio).days + 1 > MAX_DIAS_PERIODO:
        return {"erro": f"Consulte no maximo {MAX_DIAS_PERIODO} dias por vez."}
    resultado = clientes.compras(conexao, usuario, e.cliente_id, periodo)
    return resultado if resultado is not None else {"nao_encontrado": clientes.NAO_ENCONTREI}


class EntradaRanking(_Entrada):
    inicio: date | None = Field(
        default=None,
        description="Primeiro dia, AAAA-MM-DD; vazio se o vendedor nao disse (padrao: 90 dias)",
    )
    fim: date | None = Field(
        default=None,
        description="Ultimo dia, AAAA-MM-DD; vazio se o vendedor nao disse (padrao: hoje)",
    )
    limite: int = Field(default=5, ge=1, le=LIMITE_LISTA)


def clientes_que_mais_compram(
    conexao: Connection, usuario: UsuarioAtual, e: EntradaRanking
) -> dict:
    fim = min(e.fim or _hoje(), _hoje())
    inicio = e.inicio or fim - timedelta(days=DIAS_DO_RANKING - 1)
    if inicio > fim:
        return {"erro": "O inicio precisa ser antes do fim."}
    if (fim - inicio).days + 1 > MAX_DIAS_RANKING:
        return {"erro": f"Consulte no maximo {MAX_DIAS_RANKING} dias por vez."}
    id_loja = _loja_da_venda(conexao, usuario)
    ranking = vendas_repositorio.clientes_que_mais_compram(
        conexao, id_loja, STATUS_DE_VENDA, inicio, fim, limit=e.limite
    )
    padroes = []
    if e.inicio is None:
        padroes.append(f"período padrão dos últimos {DIAS_DO_RANKING} dias")
    if "limite" not in e.model_fields_set:
        padroes.append(f"os {e.limite} primeiros")
    return {
        "inicio": inicio.isoformat(),
        "fim": fim.isoformat(),
        "criterio": CRITERIO_VENDAS + " Valor comprado nesta loja.",
        "padroes_usados": padroes,
        "ordem": "ja ordenado do maior para o menor total; mantenha esta ordem",
        "clientes": [
            {
                "posicao": posicao,
                "nome": c["nome"],
                "pedidos": int(c["pedidos"]),
                "total": _dinheiro(c["total"]),
                "ultima_compra": c["ultima_compra"].date().isoformat(),
            }
            for posicao, c in enumerate(ranking, start=1)
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


TextoFiltro = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]


class EntradaEstoque(_Entrada):
    tamanho: TextoFiltro | None = Field(
        default=None, description="Tamanho como o vendedor falou (ex.: G, tam g, grande, 38)"
    )
    categoria: TextoFiltro | None = Field(
        default=None,
        description=(
            "Tipo de peca como o vendedor falou (ex.: camisa, calcas, vestidos). Para 'roupas', "
            "'pecas' ou sem tipo, deixe vazio ou mande 'roupas'"
        ),
    )
    cor: TextoFiltro | None = Field(default=None, description="Cor, so se o vendedor disse")
    marca: TextoFiltro | None = Field(default=None, description="Marca, so se o vendedor disse")
    produto: TextoFiltro | None = Field(
        default=None, description="Nome do modelo, so se o vendedor disse (ex.: linho, modena)"
    )
    agrupar_por: Literal["nenhum", "tamanho", "categoria", "cor", "produto"] | None = Field(
        default=None, description="Detalhar o total por tamanho, categoria, cor ou produto"
    )


def _descricao_dos_filtros(f: estoque_vendedor.Filtro, e: EntradaEstoque) -> str:
    partes = []
    if f.tamanho:
        partes.append(f"tamanho {f.tamanho}")
    if f.categorias is not None:
        partes.append(
            "todas as categorias" if len(f.categorias) > 1 else f"categoria {f.categorias[0]}"
        )
    for nome in ("cor", "marca", "produto"):
        if getattr(e, nome):
            partes.append(f"{nome} contendo '{getattr(e, nome)}'")
    return ", ".join(partes) or "sem filtro"


def consultar_estoque(conexao: Connection, usuario: UsuarioAtual, e: EntradaEstoque) -> dict:
    """Unidades disponiveis na loja do vendedor, com filtros normalizados e soma no SQL."""
    id_loja = _loja_da_venda(conexao, usuario)
    cat = estoque_vendedor.catalogo(conexao)
    n = estoque_vendedor.Normalizacao()
    if e.tamanho:
        estoque_vendedor.normalizar_tamanho(e.tamanho, cat, n)
    if e.categoria:
        estoque_vendedor.normalizar_categoria(e.categoria, cat, n)
    validos = {"tamanhos": list(cat.tamanhos), "categorias": list(cat.categorias)}
    if n.invalidos:
        # Filtro que nao existe nao e "zero": o modelo corrige o valor ou diz que ele nao existe.
        return {
            "filtro_invalido": n.invalidos,
            "valores_validos": validos,
            "normalizacoes_tentadas": n.tentativas,
            "orientacao": (
                "Nenhuma contagem foi feita. Se houver um valor valido equivalente, consulte de "
                "novo com ele; senao, diga que esse valor nao existe e cite os validos."
            ),
        }
    filtro = estoque_vendedor.Filtro(id_loja, n.tamanho, n.categorias, e.cor, e.marca, e.produto)
    agrupar = e.agrupar_por or (
        "categoria" if n.categorias is None or len(n.categorias) > 1 else "nenhum"
    )
    contagem = estoque_vendedor.contar(conexao, filtro, agrupar)
    saida = {
        "loja": vendas_repositorio.nome_da_loja(conexao, id_loja),
        "filtros_aplicados": _descricao_dos_filtros(filtro, e),
        "criterio": "Unidades disponiveis (quantidade acima de zero) de pecas ativas na loja.",
        "total_unidades": contagem["unidades"],
        "total_modelos": contagem["modelos"],
        "total_skus": contagem["skus"],
        "detalhamento": contagem["detalhamento"],
        "limite_aplicado": estoque_vendedor.LIMITE_DETALHAMENTO
        if contagem["detalhamento"]
        else None,
        "truncado": contagem["truncado"],
    }
    if n.tentativas:
        saida["normalizacoes_tentadas"] = n.tentativas
    if contagem["unidades"] == 0:
        # Zero com filtro valido: e zero de verdade, mas vai junto o que existe para conferir.
        saida["zero_confirmado"] = True
        saida["valores_validos"] = validos
    return saida


class EntradaResumoEstoque(_Entrada):
    dia: date | None = Field(
        default=None, description="Saldo no fim deste dia, formato AAAA-MM-DD (padrao: agora)"
    )


def resumo_do_estoque(conexao: Connection, usuario: UsuarioAtual, e: EntradaResumoEstoque) -> dict:
    """Os mesmos totais do topo da tela Saldo de estoque, na loja do token."""
    if e.dia is not None and e.dia > _hoje():
        return {"erro": "O dia nao pode ser depois de hoje."}
    id_loja = estoque.loja_do_escopo(usuario, None)
    resumo = estoque_repositorio.resumo_do_saldo(conexao, id_loja, e.dia)
    return {
        "dia": (e.dia or _hoje()).isoformat(),
        "criterio": "Saldo da sua loja; o valor usa o preco de venda de hoje.",
        "unidades_em_estoque": int(resumo["unidades"]),
        "produtos": int(resumo["produtos"]),
        "skus": int(resumo["pecas"]),
        "skus_com_estoque_baixo": int(resumo["estoque_baixo"]),
        "skus_esgotados": int(resumo["esgotadas"]),
        "valor_em_estoque_a_preco_de_venda": _dinheiro(resumo["valor_em_estoque"]),
    }


class EntradaAlerta(_Entrada):
    situacao: Literal["baixo", "esgotado"] = Field(
        description="baixo = no minimo ou abaixo; esgotado = sem nenhuma unidade"
    )
    limite: int = Field(default=10, ge=1, le=LIMITE_PECAS)


def pecas_em_alerta(conexao: Connection, usuario: UsuarioAtual, e: EntradaAlerta) -> dict:
    filtro = FiltroSaldo(id_loja=estoque.loja_do_escopo(usuario, None), situacao=e.situacao)
    total, itens = estoque_repositorio.itens_do_saldo(conexao, filtro, limit=e.limite, offset=0)
    return {
        "situacao": e.situacao,
        "total": total,
        "pecas": [
            {
                "sku": i["sku"],
                "produto": i["produto"],
                "cor": i["cor"],
                "tamanho": i["tamanho"],
                "quantidade": int(i["total"]),
                "minimo": int(i["minimo_total"]),
            }
            for i in itens
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


# Espelha as telas do vendedor no front (src/lib/navegacao.ts e src/pages/painel/vendas|estoque).
# Mudou um botao ou uma aba la, atualize aqui.
GUIA_DO_PAINEL = {
    "menu": (
        "No computador, o menu fica na barra azul do lado esquerdo da tela (passe o mouse sobre "
        "ela para ver os nomes); no celular, nos botoes logo abaixo do topo. O vendedor ve tres "
        "secoes, nesta ordem: Estoque, Vendas e Clientes. O botao redondo no canto inferior "
        "direito abre este assistente."
    ),
    "vendas": (
        "Tela Vendas (no menu, clique em Vendas): lista as vendas da sua loja, com as colunas "
        "Venda, Cliente, Vendedor, Pecas, Total e Situacao. No campo Buscar, digite o numero da "
        "venda, parte do nome do cliente ou o CPF completo do cliente. Clique numa linha para ver "
        "a data, a forma de pagamento e as pecas da venda. A tela nao tem filtro de data nem "
        "mostra o total vendido no dia ou no mes."
    ),
    "nova_venda": (
        "Lancar uma venda: no menu, clique em Vendas e depois no botao Nova venda (no alto da "
        "tela). 1) Em CPF do cliente, digite o CPF e clique em Buscar. 2) Em Buscar peca, digite "
        "nome, SKU ou codigo de barras e clique em Adicionar em cada peca (Tirar remove). 3) "
        "Escolha a forma de pagamento. 4) Se for troca, escreva 'troca' em Observacao "
        "(opcional). 5) Clique em Lancar venda."
    ),
    "clientes": (
        "Tela Clientes (no menu, clique em Clientes): lista os clientes da sua loja (cadastrados "
        "nela ou que ja compraram nela) que tem CPF cadastrado, com as colunas Cliente (nome e "
        "e-mail), CPF (so os dois ultimos digitos), Telefone, Cidade e Desde. Para achar um "
        "cliente especifico, use o campo Buscar: aceita parte do nome, do e-mail ou do telefone, "
        "ou o CPF completo. As linhas nao abrem detalhes; para ver as compras de um cliente, va "
        "em Vendas e busque pelo nome ou CPF dele."
    ),
    "estoque": (
        "Tela Saldo de estoque (no menu, clique em Estoque; abre na aba Saldo): no topo, quatro "
        "quadros com os totais da loja: Unidades em estoque, SKUs com estoque baixo, SKUs "
        "esgotados e Valor em estoque (a preco de venda). Filtros: Buscar (nome ou SKU), "
        "Categoria, Saldo em (para ver o fim de um dia passado) e Situacao (OK, Estoque baixo, "
        "Esgotado). Clique numa peca para ver o Saldo por loja e o Historico de movimentacoes."
    ),
    "conta": (
        "No canto superior direito fica o botao da conta (suas iniciais e seu nome). Clique nele "
        "para abrir o menu; la fica Sair da conta."
    ),
    "nao_e_do_vendedor": (
        "Movimentar estoque (entrada, saida, ajuste), transferencias, aprovacoes, atendimento e "
        "gestao nao aparecem para o vendedor: fale com o gerente da loja."
    ),
}


def guia_do_painel(conexao: Connection, usuario: UsuarioAtual, e: EntradaVazia) -> dict:
    return {"telas": GUIA_DO_PAINEL}


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
    "clientes_que_mais_compram": (
        "Ranking dos clientes que mais compraram na loja num periodo (padrao: ultimos 90 dias), "
        "com total, numero de pedidos e ultima compra. Use para 'melhores clientes'.",
        EntradaRanking,
        clientes_que_mais_compram,
    ),
    "buscar_clientes": (
        "Procura clientes da loja (cadastrados nela ou com compra nela) por nome, e-mail ou CPF.",
        EntradaBuscaClientes,
        buscar_clientes,
    ),
    "consultar_estoque": (
        "CONTA o estoque da loja: total de unidades e de modelos, com filtro opcional de "
        "tamanho, tipo de peca (categoria), cor, marca ou nome do modelo, e detalhamento. Use "
        "para toda pergunta de quantidade ('quantas pecas G', 'tem camisa G?', 'sobrou GG?', "
        "'estoque do M'). Mande os filtros como o vendedor falou: o servidor normaliza.",
        EntradaEstoque,
        consultar_estoque,
    ),
    "consultar_pecas": (
        "Lista pecas de um modelo especifico (nome ou SKU obrigatorio) com preco e quantidade de "
        "cada cor e tamanho. Nao use para contar ou somar estoque: para isso, consultar_estoque.",
        EntradaPecas,
        consultar_pecas,
    ),
    "resumo_do_estoque": (
        "Totais do estoque da loja: unidades em estoque, produtos, SKUs, SKUs com estoque baixo, "
        "SKUs esgotados e valor em estoque a preco de venda (agora ou no fim de um dia). Use para "
        "'quantas unidades temos no total' e 'quanto vale o estoque'.",
        EntradaResumoEstoque,
        resumo_do_estoque,
    ),
    "pecas_em_alerta": (
        "Lista as pecas da loja com estoque baixo (no minimo ou abaixo) ou esgotadas.",
        EntradaAlerta,
        pecas_em_alerta,
    ),
    "guia_do_painel": (
        "Caminho de cliques no painel do vendedor: onde ficam vendas, nova venda, clientes, "
        "estoque e conta, e como usar cada tela. Use para 'onde vejo', 'como faco', 'onde fica'.",
        EntradaVazia,
        guia_do_painel,
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
    # Consultas de cliente: so vao ao modelo quando a pergunta e sobre um cliente.
    "buscar_cliente": (
        "Acha um cliente da loja por nome, e-mail ou CPF e traz so os campos pedidos.",
        EntradaBuscarCliente,
        buscar_cliente,
    ),
    "compras_do_cliente": (
        "Pedidos, itens e totais de um cliente (cliente_id de buscar_cliente) num dia ou periodo.",
        EntradaCompras,
        compras_do_cliente,
    ),
}
CONSULTA_CLIENTE = ("buscar_cliente", "compras_do_cliente")


# O modelo tende a "ajudar" pedindo 10 itens ou um periodo que o vendedor nao disse. Sem um
# numero ou uma palavra de tempo na pergunta, esses argumentos caem e vale o padrao da ferramenta
# (que volta em `padroes_usados` para a resposta dizer qual foi).
_PEDE_QUANTIDADE = re.compile(
    r"\d|\b(dois|duas|tres|quatro|cinco|seis|sete|oito|nove|dez|quinze|vinte)\b"
)
_PEDE_PERIODO = re.compile(
    r"\d{1,2}/\d{1,2}|\d{4}-\d{2}|\b20\d\d\b|\b(hoje|ontem|anteontem|semana|semanas|mes|meses|ano|anos|dia|dias|periodo|trimestre|"
    r"semestre|desde|janeiro|fevereiro|marco|abril|maio|junho|julho|agosto|setembro|outubro|"
    r"novembro|dezembro|natal|black friday)\b"
)
_ARGUMENTOS_DE_QUANTIDADE = {"limite"}
_ARGUMENTOS_DE_PERIODO = {"inicio", "fim", "dia"}


def so_o_que_foi_pedido(pergunta: str, argumentos: dict[str, Any]) -> dict[str, Any]:
    texto = _normal(pergunta)
    tirar = set()
    if not _PEDE_QUANTIDADE.search(texto):
        tirar |= _ARGUMENTOS_DE_QUANTIDADE
    if not _PEDE_PERIODO.search(texto):
        tirar |= _ARGUMENTOS_DE_PERIODO
    return {k: v for k, v in argumentos.items() if k not in tirar}


def _tipo_base(anotacao: Any) -> Any:
    """`int | None`, `Annotated[str, ...]` -> int, str (o tipo que o modelo precisa mandar)."""
    if isinstance(anotacao, type):
        return anotacao
    for argumento in get_args(anotacao):
        tipo = _tipo_base(argumento)
        if tipo is not None and tipo is not type(None):
            return tipo
    return None


def _limites(campo: Any) -> tuple[Any, Any]:
    minimo = next((m.ge for m in campo.metadata if getattr(m, "ge", None) is not None), None)
    maximo = next((m.le for m in campo.metadata if getattr(m, "le", None) is not None), None)
    return minimo, maximo


def _tolerar(modelo: type[_Entrada], argumentos: dict[str, Any]) -> dict[str, Any]:
    """Os modelos mandam `""` para "sem filtro" e pedem mais itens que o maximo. Em vez de gastar
    uma rodada com erro: texto vazio vira ausente e numero fora da faixa vai para o limite."""
    ajustados = {}
    for nome, valor in argumentos.items():
        if valor is None or (isinstance(valor, str) and not valor.strip()):
            continue
        campo = modelo.model_fields.get(nome)
        if campo is not None and _tipo_base(campo.annotation) is int and isinstance(valor, int):
            minimo, maximo = _limites(campo)
            valor = max(valor, minimo) if minimo is not None else valor
            valor = min(valor, maximo) if maximo is not None else valor
        ajustados[nome] = valor
    return ajustados


def _parametros(modelo: type[_Entrada]) -> dict[str, Any]:
    """JSON Schema simples (tipos basicos) aceito pelos dois provedores."""
    propriedades: dict[str, Any] = {}
    obrigatorios = []
    for nome, campo in modelo.model_fields.items():
        lista = get_origin(campo.annotation) is list
        anotacao = get_args(campo.annotation)[0] if lista else campo.annotation
        tipo = _tipo_base(anotacao)
        propriedade: dict[str, Any] = {"type": "integer" if tipo is int else "string"}
        literal = next(
            (a for a in (anotacao, *get_args(anotacao)) if get_origin(a) is Literal),
            None,
        )
        if literal is not None:
            propriedade["enum"] = list(get_args(literal))
        if lista:
            propriedade = {"type": "array", "items": propriedade}
        if campo.description:
            propriedade["description"] = campo.description
        minimo, maximo = _limites(campo)
        if tipo is int and minimo is not None:
            propriedade["minimum"] = minimo
        if tipo is int and maximo is not None:
            propriedade["maximum"] = maximo
        propriedades[nome] = propriedade
        if campo.is_required():
            obrigatorios.append(nome)
    schema: dict[str, Any] = {"type": "object", "properties": propriedades}
    if obrigatorios:
        schema["required"] = obrigatorios
    return schema


def ferramenta(nome: str) -> Ferramenta:
    desc, modelo, _ = _REGISTRO[nome]
    return Ferramenta(nome, desc, _parametros(modelo))


# Catalogo das perguntas gerais; as de cliente recebem so as delas (`ferramentas_de_cliente`).
FERRAMENTAS = [ferramenta(nome) for nome in _REGISTRO if nome not in CONSULTA_CLIENTE]


# Pergunta de cliente: o modelo so recebe a busca. Nas de compras, o backend emenda as compras do
# dia no resultado da busca (ver `consulta_cliente`), o que poupa uma ida e volta ao modelo.
FERRAMENTAS_DE_CLIENTE = [ferramenta("buscar_cliente")]


def executar(
    conexao: Connection, usuario: UsuarioAtual, nome: str, argumentos: dict[str, Any]
) -> dict:
    """Valida e executa uma ferramenta da allowlist. Nunca levanta: erro vira `{"erro": ...}`."""
    item = _REGISTRO.get(nome)
    if item is None:
        return {"erro": "Ferramenta desconhecida."}
    _, modelo, funcao = item
    try:
        entrada = modelo.model_validate(_tolerar(modelo, argumentos))
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
