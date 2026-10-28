"""Separa pergunta de navegacao ("onde vejo X", "como acesso Y") de pergunta de dados.

A decisao e do backend, por regra fixa, e nao do modelo: pergunta de navegacao vai para o modelo
rapido so com o mapa das telas e nenhuma ferramenta de dados. Assim "onde ver os clientes" nunca
vira um ranking de clientes.
"""

import re
import unicodedata
from dataclasses import dataclass


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


def classificar(pergunta: str) -> Intencao:
    texto = _normalizar(pergunta)
    if _LOJA_FISICA.search(texto) and not re.search(r"\b(tela|aba|menu|botao|painel)\b", texto):
        return Intencao(navegacao=False)
    if not any(p.search(texto) for p in _NAVEGACAO):
        return Intencao(navegacao=False)
    return Intencao(navegacao=True, tambem_pede_dados=bool(_DADOS.search(texto)))
