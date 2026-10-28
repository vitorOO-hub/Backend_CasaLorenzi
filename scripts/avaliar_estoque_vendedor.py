"""Golden set das perguntas de estoque do assistente do vendedor, contra o modelo REAL.

Fora do CI de proposito: chama Groq/Gemini (custa e depende da chave e do limite do provedor).
Roda o mesmo fluxo do chat (intencao, roteamento, ferramentas, conferencia), sem gravar conversa,
e compara a resposta com a contagem tirada direto do banco por uma consulta independente.

Uso (na raiz do backend):
    .venv/Scripts/python.exe scripts/avaliar_estoque_vendedor.py [--loja <id_loja>] [--saida x.md]

Por padrao usa a loja Casa Lorenzi Centro. Cada pergunta espera alguns segundos para nao
estourar o limite por minuto do Groq.
"""

import argparse
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.assistente.roteamento import planejar_pergunta  # noqa: E402
from app.assistente.vendedor import (  # noqa: E402
    conferencia,
    intencao,
    service,  # noqa: E402
)
from app.assistente.vendedor import ferramentas as ferramentas_vendedor  # noqa: E402
from app.assistente.vendedor.provedores import ErroDoProvedor, Turno, provedor_para  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.core.db import get_engine  # noqa: E402
from app.core.papeis import Papel, UsuarioAtual  # noqa: E402

LOJA_CENTRO = UUID("94de7e65-d3b5-425f-8b82-ff12590030e4")
PAUSA_SEGUNDOS = 20
TODAS = "todas"  # "roupas", "pecas": tudo menos pendente_identificacao


@dataclass(frozen=True)
class Caso:
    pergunta: str
    tamanho: str | None = None
    categorias: tuple[str, ...] | str | None = None
    cor: str | None = None
    produto: str | None = None
    # O tamanho pedido nao existe no catalogo: a resposta nao pode virar "zero".
    tamanho_invalido: bool = False


CASOS = [
    Caso("quantas roupas do tamanho G tem?", "G", TODAS),
    Caso("quantas reoupas do tamanho G tem?", "G", TODAS),
    Caso("quantas peças G tem", "G", TODAS),
    Caso("estoque do G", "G"),
    Caso("tem peça tamanho g?", "G", TODAS),
    Caso("quantas pecas tamanho g sem acento", "G", TODAS),
    Caso("tamanho grande, quantas peças tem?", "G", TODAS),
    Caso("qtas pçs G?", "G", TODAS),
    Caso("quantas unidades no tamanho M?", "M"),
    Caso("quantas roupas tamanho medio?", "M", TODAS),
    Caso("quantas peças P temos?", "P", TODAS),
    Caso("sobrou tamanho gg?", "GG"),
    Caso("quantas peças PP tem?", "PP", TODAS),
    Caso("tem camisa G?", "G", ("camisa",)),
    Caso("quantas camisas tamanho G", "G", ("camisa",)),
    Caso("quantas calças no G?", "G", ("calça",)),
    Caso("quantos vestidos G temos?", "G", ("vestido",)),
    Caso("quantas saias tamanho G?", "G", ("saia",)),
    Caso("trico no G, quantos tem?", "G", ("tricô",)),
    Caso("quantas jaquetas G?", "G", ("jaqueta",)),
    Caso("quantas camisetas tamanho P?", "P", ("camiseta",)),
    Caso("quantas camisas temos no total?", None, ("camisa",)),
    Caso("quantas camsias tem?", None, ("camisa",)),
    Caso("quantas peças pretas tem?", None, TODAS, cor="preto"),
    Caso("quantas peças azuis no G?", "G", TODAS, cor="azul"),
    Caso("quantas unidades de calçado tem?", None, ("calçado",)),
    Caso("quantos acessórios temos?", None, ("acessório",)),
    Caso("quantas peças tamanho 90?", "90"),
    Caso("quantas camisas de linho G?", "G", ("camisa",), produto="linho"),
    Caso("quantos blazer modena G tem?", "G", None, produto="blazer modena"),
    Caso("quantas peças G por categoria?", "G", TODAS),
    Caso("quantas peças tamanho XG?", "XG", tamanho_invalido=True),
]


def _normal(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.casefold())
    return "".join(c for c in texto if not unicodedata.combining(c))


def esperado(conexao, id_loja: UUID, caso: Caso) -> int:
    """Contagem independente da ferramenta: SQL direto, unidades disponiveis (> 0)."""
    condicoes = ["e.id_loja = :loja", "e.quantidade > 0", "va.ativa", "pr.ativo"]
    parametros: dict = {"loja": str(id_loja)}
    if caso.tamanho:
        condicoes.append("va.tamanho = :tamanho")
        parametros["tamanho"] = caso.tamanho
    if caso.categorias == TODAS:
        condicoes.append("pr.categoria <> 'pendente_identificacao'")
    elif caso.categorias:
        condicoes.append("pr.categoria = ANY(:categorias)")
        parametros["categorias"] = list(caso.categorias)
    if caso.cor:
        condicoes.append("va.cor ILIKE :cor")
        parametros["cor"] = f"%{caso.cor}%"
    for i, palavra in enumerate((caso.produto or "").split()):
        condicoes.append(f"pr.nome ILIKE :p{i}")
        parametros[f"p{i}"] = f"%{palavra}%"
    sql = (
        "SELECT COALESCE(sum(e.quantidade), 0) FROM estoque e "
        "JOIN variacao_produto va ON va.id_variacao = e.id_variacao "
        "JOIN produto pr ON pr.id_produto = va.id_produto WHERE " + " AND ".join(condicoes)
    )
    return int(conexao.execute(text(sql), parametros).scalar_one())


def _numeros(resposta: str) -> set[int]:
    sem_milhar = re.sub(r"(?<=\d)[.\s  ](?=\d{3}\b)", "", resposta)
    return {int(n) for n in re.findall(r"(?<![\d,])\d+(?![\d,])", sem_milhar)}


_DIZ_ZERO = re.compile(
    r"\b(nao ha|nao temos|nao tem|nenhum|nenhuma|zero|sem estoque|esgotad|nao encontrei)"
)


@dataclass
class Resultado:
    caso: Caso
    esperado: int
    resposta: str = ""
    ferramentas: list = field(default_factory=list)
    passou: bool = False
    motivo: str = ""


def avaliar(caso: Caso, valor: int, resposta: str) -> tuple[bool, str]:
    if resposta.startswith("(erro do provedor"):
        return False, "provedor fora (limite de uso), nao avaliado"
    texto = _normal(resposta)
    numeros = _numeros(resposta)
    if caso.tamanho_invalido:
        if re.search(r"\b0\b", texto) or "nao ha" in texto and "tamanho" not in texto:
            return False, "tratou tamanho inexistente como zero"
        return True, ""
    if valor == 0:
        return (True, "") if _DIZ_ZERO.search(texto) or 0 in numeros else (False, "nao disse zero")
    if valor not in numeros:
        return False, f"numero esperado {valor} ausente"
    if _DIZ_ZERO.search(texto) and not re.search(rf"\b{valor}\b", texto):
        return False, "disse que nao ha"
    return True, ""


def responder(conexao, usuario: UsuarioAtual, pergunta: str, settings: Settings):
    """Mesmo fluxo de `service.enviar_mensagem`, sem gravar conversa."""
    pedido = intencao.classificar(pergunta)
    if pedido.navegacao:
        return "(caiu em navegacao)", []
    plano = planejar_pergunta(pergunta, settings)
    if plano.destino is None:
        return f"(sem destino: {plano.estado})", []
    nome_da_loja = service.vendas_repositorio.nome_da_loja(conexao, usuario.id_loja)
    sistema = service.SISTEMA.format(loja=nome_da_loja, hoje=time.strftime("%d/%m/%Y"))
    chamadas = []

    def executar(nome, argumentos):
        argumentos = ferramentas_vendedor.so_o_que_foi_pedido(pergunta, argumentos)
        saida = ferramentas_vendedor.executar(conexao, usuario, nome, argumentos)
        chamadas.append((nome, argumentos))
        return saida

    for tentativa in range(3):
        try:
            resultado = provedor_para(plano.destino, settings).conversar(
                plano.destino.modelo,
                sistema,
                [Turno("usuario", pergunta)],
                ferramentas_vendedor.FERRAMENTAS,
                executar,
                max_rodadas=service.MAX_RODADAS_DE_FERRAMENTA,
                max_tokens=service.MAX_TOKENS_DE_SAIDA,
            )
            break
        except ErroDoProvedor as erro:
            if erro.status != 429 or tentativa == 2:
                return f"(erro do provedor: {erro.status})", chamadas
            time.sleep(30)
    texto = conferencia.conferir(resultado.texto, resultado.chamadas) or resultado.texto
    return texto, chamadas


def main() -> None:
    argumentos = argparse.ArgumentParser()
    argumentos.add_argument("--loja", type=UUID, default=LOJA_CENTRO)
    argumentos.add_argument("--saida", type=Path)
    argumentos.add_argument("--so", type=int, help="roda so os N primeiros casos")
    argumentos.add_argument("--de", type=int, default=1, help="comeca no caso N (1 = o primeiro)")
    argumentos.add_argument(
        "--modelo",
        help="forca um destino provedor:modelo nas duas rotas (ex.: gemini:gemini-3.5-flash-lite)",
    )
    opcoes = argumentos.parse_args()

    forcado = (
        {"assistente_modelo_rapido": opcoes.modelo, "assistente_modelo_preciso": opcoes.modelo}
        if opcoes.modelo
        else {}
    )
    settings = Settings(**forcado)
    usuario = UsuarioAtual(id_auth=UUID(int=0), papel=Papel.VENDEDOR, id_loja=opcoes.loja)
    resultados: list[Resultado] = []
    with get_engine(settings).connect() as conexao:
        for caso in CASOS[opcoes.de - 1 : opcoes.so]:
            r = Resultado(caso, esperado(conexao, opcoes.loja, caso))
            r.resposta, r.ferramentas = responder(conexao, usuario, caso.pergunta, settings)
            r.passou, r.motivo = avaliar(caso, r.esperado, r.resposta)
            resultados.append(r)
            print(f"{'OK ' if r.passou else 'FALHOU'} | {caso.pergunta} | esperado {r.esperado}")
            time.sleep(PAUSA_SEGUNDOS)
        conexao.rollback()

    linhas = [
        "| # | Pergunta | Esperado | Passou | Ferramentas | Resposta |",
        "|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(resultados, start=1):
        esperado_txt = "tamanho invalido" if r.caso.tamanho_invalido else str(r.esperado)
        ferramentas = "; ".join(f"{n} {a}" for n, a in r.ferramentas) or "-"
        resposta = r.resposta.replace("\n", " ").replace("|", "/")[:220]
        situacao = "sim" if r.passou else f"NAO ({r.motivo})"
        linhas.append(
            f"| {i} | {r.caso.pergunta} | {esperado_txt} | {situacao} | {ferramentas} "
            f"| {resposta} |"
        )
    passou = sum(r.passou for r in resultados)
    linhas.append(f"\n**{passou}/{len(resultados)} passaram.**")
    relatorio = "\n".join(linhas)
    print(relatorio)
    if opcoes.saida:
        opcoes.saida.write_text(relatorio, encoding="utf-8")


if __name__ == "__main__":
    main()
