"""Separa pergunta de navegacao ("onde vejo X", "como acesso Y") de pergunta de dados.

A decisao e do backend, por regra fixa, e nao do modelo: pergunta de navegacao vai para o modelo
rapido so com o mapa das telas e nenhuma ferramenta de dados. Assim "onde ver os clientes" nunca
vira um ranking de clientes.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.casefold())
    return " ".join("".join(c for c in texto if not unicodedata.combining(c)).split())


_VERBO_DE_TELA = (
    r"(ver|vejo|veja|enxergar|acho|achar|encontro|encontrar|acesso|acessar|abro|abrir|consulto|"
    r"consultar|cadastro|cadastrar|lanco|lancar|registro|registrar|filtro|filtrar|busco|buscar|"
    r"pesquiso|pesquisar|mudo|mudar|troco|trocar|clico|clicar|saio|sair)"
)
# "Como estao as vendas" e "onde esta o pedido 123" sao dados: "esta" fica de fora, e "fica" so
# vale depois de "onde" ("onde fica a tela de...", mas nao "como fica o estoque").
_NAVEGACAO = (
    # onde vejo / onde posso ver / onde eu acho / onde fica
    re.compile(
        rf"\b(onde|aonde)\s+(que\s+)?(eu\s+)?((posso|consigo|da para|da pra)\s+)?"
        rf"({_VERBO_DE_TELA}|fica|ficam)\b"
    ),
    # como faco pra ver / como eu acesso / como consigo lancar
    re.compile(
        rf"\bcomo\s+(que\s+)?(eu\s+)?((faco|faz|posso|consigo|da)\s+)?((pra|para)\s+)?"
        rf"{_VERBO_DE_TELA}\b"
    ),
    # em qual tela / qual aba / que menu
    re.compile(r"\b(em\s+)?(qual|que|quais)\s+(tela|aba|menu|botao|pagina|secao|lugar)\b"),
    re.compile(r"\b(tela|aba|menu|botao)\s+(de|do|da|dos|das|para|pra)\b"),
)
# "Onde fica a loja X" e endereco de loja fisica (dado), nao uma tela do painel.
_LOJA_FISICA = re.compile(
    r"\b(onde|aonde)\s+(fica|ficam|esta|estao)\s+(a|as|o|os)?\s*(loja|lojas|unidade|unidades|filial)\b"
)
_DADOS = re.compile(
    r"\b(quais|qual foi|quanto|quantos|quantas|me mostre|mostre|mostra|liste|listar|lista os|"
    r"ranking|top|maiores|melhores|mais vendid\w*|mais compr\w*|total)\b"
)


@dataclass(frozen=True)
class Intencao:
    navegacao: bool
    # A pergunta de navegacao tambem pede dados ("onde vejo quanto vendemos hoje?").
    tambem_pede_dados: bool = False


_CAMPOS_DE_CLIENTE = {
    "cpf": re.compile(r"\bcpf\b"),
    "email": re.compile(r"\be-? ?mail\b"),
    "telefone": re.compile(r"\b(telefone|celular|fone|whatsapp|whats|zap)\b"),
}
_COMPRAS_DO_CLIENTE = re.compile(
    r"\b(comprou|levou|gastou)\b|"
    r"\b(compras?|pedidos?)\s+(do|da)\s+(?!(dia|mes|semana|loja|periodo|ano|hoje)\b)\w"
)
# "Quem comprou mais" e ranking (outra ferramenta), nao a consulta de um cliente.
_RANKING = re.compile(r"\b(quem|quais clientes|ranking|mais compr\w*|melhores|top)\b")
# O que sobra da pergunta sem estas palavras e (ou contem) o cliente.
_SEM_CLIENTE = set(
    """
    qual quais o a os as e ou um uma do da de dos das no na nos nas em pra para por com que oque
    cliente clientes cpf email mail e-mail telefone celular fone whatsapp whats zap contato numero
    comprou levou gastou compra compras pedido pedidos item itens total valor quanto quanta quantos
    quantas foi foram me passa passe manda mande diz diga fala fale mostra mostre informe ver saber
    tem ta esta eh e qual hoje ontem anteontem dia dias semana mes ano passado passada este esse
    esta essa neste nesse nesta nessa janeiro fevereiro marco abril maio junho julho agosto setembro
    outubro novembro dezembro dele dela desse dessa deste desta
    """.split()
)


@dataclass(frozen=True)
class ConsultaCliente:
    """Pergunta sobre um cliente: um dado do cadastro (CPF, e-mail, telefone) ou as compras."""

    tipo: Literal["campos", "compras"]
    campos: tuple[str, ...]
    # A pergunta diz quem e o cliente (nome, e-mail ou CPF)? Sem isso, o chat pergunta antes.
    tem_cliente: bool


def consulta_de_cliente(pergunta: str) -> ConsultaCliente | None:
    texto = _normalizar(pergunta)
    if _RANKING.search(texto):
        return None
    campos = tuple(campo for campo, padrao in _CAMPOS_DE_CLIENTE.items() if padrao.search(texto))
    if _COMPRAS_DO_CLIENTE.search(texto):
        tipo = "compras"
    elif campos:
        tipo = "campos"
    else:
        return None
    sobra = [
        p
        for p in re.findall(r"[a-z]+|\S+@\S+|\d[\d.\-/]*", texto)
        if p not in _SEM_CLIENTE and not re.fullmatch(r"\d{1,2}([/.-]\d{1,4}){0,2}", p)
    ]
    return ConsultaCliente(tipo, campos, tem_cliente=bool(sobra))


def classificar(pergunta: str) -> Intencao:
    texto = _normalizar(pergunta)
    if _LOJA_FISICA.search(texto) and not re.search(r"\b(tela|aba|menu|botao|painel)\b", texto):
        return Intencao(navegacao=False)
    if not any(p.search(texto) for p in _NAVEGACAO):
        return Intencao(navegacao=False)
    return Intencao(navegacao=True, tambem_pede_dados=bool(_DADOS.search(texto)))
