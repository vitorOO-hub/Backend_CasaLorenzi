"""Classifica perguntas para um piloto de roteamento sem chamar provedores."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal


Rota = Literal["rapida", "precisa", "esclarecer"]


@dataclass(frozen=True)
class ClassificacaoPergunta:
    rota: Rota
    complexidade: Literal["simples", "complexa", "incompleta"]
    requer_ferramenta: bool
    motivos: tuple[str, ...]


def _normalizar(texto: str) -> str:
    decomposed = unicodedata.normalize("NFKD", texto.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


_PADROES_FERRAMENTA = (
    re.compile(r"\b(estoque|disponibilidade|quantas unidades|quantidade de)\b"),
    re.compile(r"\b(pontos?|saldo de pontos)\b"),
    re.compile(r"\b(meu|minha)\s+(pedido|compra|entrega|saldo)\b"),
    re.compile(r"\b(status|rastreio|acompanhar)\b.*\b(pedido|entrega|compra)\b"),
    re.compile(r"\b(preco|custa|valor)\b.*\b(peca|produto|sku|camiseta|calca)\b"),
    re.compile(r"\b(vendas|faturamento|pedidos)\b.*\b(ultimos?|ultimas?|periodo|semana|mes(?:es)?|dias|total)\b"),
    re.compile(r"\b(compare|comparar|diferenca|tendencia)\b.*\b(vendas|faturamento|pedidos)\b"),
    re.compile(r"\b(horario|funciona|abre|fecha)\b.*\b(loja|savassi|barra|ibirapuera)\b"),
    re.compile(r"\b(loja|savassi|barra|ibirapuera)\b.*\b(horario|domingo|sabado|abre|fecha)\b"),
)
_SKU = re.compile(r"\b[a-z]{2,5}-\d{3,}\b")
_CONSULTA_ESTOQUE = re.compile(
    r"\b(tem|temos|ha)\b.*\b(peca|produto|camiseta|calca|sku)\b.*\b(loja|savassi|barra|ibirapuera)\b"
)
_AMBIGUA = re.compile(
    r"\b(essa|esta|aquela|esse|este|aquele)\s+(peca|produto|sku|pedido)\b"
)
_ANALISE = re.compile(
    r"\b(compare|comparar|comparacao|diferenca|tendencia|explique|explicar|analise|"
    r"avalie|estime|estimar|preveja|recomende|recomendacao|por que|como chegamos|"
    r"causa|impacto|cenario|cenarios|estrategia)\b"
)
_SENSIVEL = re.compile(
    r"\b(pontos?|cpf|dados bancarios|bancario|pagamento|reembolso|estorno|"
    r"cancelamento|faturamento|margem|lucro|meu pedido|minha compra|meu saldo|"
    r"procon|direito do consumidor|codigo do consumidor|fora do prazo|excecao)\b"
)
_INSEGURO = re.compile(
    r"\b(ignore|desconsidere|burle)\b.*\b(regras|instrucoes|restricoes)\b|"
    r"\b(invente|revele|exponha)\b.*\b(cpf|senha|saldo bancario|dados pessoais|segredo)\b"
)


def classificar_pergunta(pergunta: str) -> ClassificacaoPergunta:
    """Escolhe a classe de capacidade; nao autoriza acesso a dados ou ferramentas."""
    texto = _normalizar(pergunta.strip())
    if not texto:
        return ClassificacaoPergunta(
            rota="esclarecer",
            complexidade="incompleta",
            requer_ferramenta=False,
            motivos=("pergunta_vazia",),
        )

    requer_ferramenta = any(p.search(texto) for p in _PADROES_FERRAMENTA)
    requer_ferramenta = requer_ferramenta or bool(_SKU.search(texto)) or bool(
        _CONSULTA_ESTOQUE.search(texto)
    )

    motivos: list[str] = []
    if _INSEGURO.search(texto):
        motivos.append("pedido_sensivel_ou_tentativa_de_burlar_regras")
    if _SENSIVEL.search(texto):
        motivos.append("dado_pessoal_financeiro_ou_decisao_sensivel")
    if _ANALISE.search(texto):
        motivos.append("analise_ou_raciocinio_multietapas")
    if texto.count("?") > 1:
        motivos.append("multiplas_perguntas")
    if len(texto) > 700:
        motivos.append("mensagem_muito_longa")

    referencia_ambigua = bool(_AMBIGUA.search(texto)) or bool(
        re.search(r"\b(tem|temos|ha)\s+(na|nesta|nessa)\s+loja\b", texto)
    )
    falta_item = referencia_ambigua and not _SKU.search(texto)
    if falta_item:
        return ClassificacaoPergunta(
            rota="esclarecer",
            complexidade="incompleta",
            requer_ferramenta=False,
            motivos=("produto_ou_pedido_nao_identificado",),
        )

    complexa = bool(motivos)
    if requer_ferramenta:
        motivos.append("depende_de_dado_atual_ou_personalizado")
    if not complexa:
        motivos.append("consulta_direta_sem_risco_ou_analise")

    return ClassificacaoPergunta(
        rota="precisa" if complexa else "rapida",
        complexidade="complexa" if complexa else "simples",
        requer_ferramenta=requer_ferramenta,
        motivos=tuple(motivos),
    )
