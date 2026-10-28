"""Classifica perguntas e planeja a rota sem chamar provedores externos."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from pydantic import SecretStr

from app.core.config import Settings

Rota = Literal["rapida", "precisa", "esclarecer"]
Provedor = Literal["gemini", "groq"]
EstadoRoteamento = Literal[
    "pronto",
    "esclarecer",
    "modelo_nao_configurado",
    "configuracao_invalida",
    "provedor_sem_chave",
]


@dataclass(frozen=True)
class ClassificacaoPergunta:
    rota: Rota
    complexidade: Literal["simples", "complexa", "incompleta"]
    requer_ferramenta: bool
    motivos: tuple[str, ...]


@dataclass(frozen=True)
class DestinoModelo:
    provedor: Provedor
    modelo: str


@dataclass(frozen=True)
class PlanoRoteamento:
    classificacao: ClassificacaoPergunta
    estado: EstadoRoteamento
    destino: DestinoModelo | None


def _normalizar(texto: str) -> str:
    decomposed = unicodedata.normalize("NFKD", texto.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


_PADROES_FERRAMENTA = (
    re.compile(r"\b(estoque|disponibilidade|quantas unidades|quantidade de)\b"),
    re.compile(r"\b(pontos?|saldo de pontos)\b"),
    re.compile(r"\b(meu|minha)\s+(pedido|compra|entrega|saldo)\b"),
    re.compile(r"\b(status|rastreio|acompanhar)\b.*\b(pedido|entrega|compra)\b"),
    re.compile(r"\b(preco|custa|valor)\b.*\b(peca|produto|sku|camiseta|calca)\b"),
    re.compile(
        r"\b(vendas|faturamento|pedidos)\b.*\b(ultimos?|ultimas?|periodo|semana|mes(?:es)?|dias|total)\b"
    ),
    re.compile(r"\b(compare|comparar|diferenca|tendencia)\b.*\b(vendas|faturamento|pedidos)\b"),
    re.compile(r"\b(horario|funciona|abre|fecha)\b.*\b(loja|savassi|barra|ibirapuera)\b"),
    re.compile(r"\b(loja|savassi|barra|ibirapuera)\b.*\b(horario|domingo|sabado|abre|fecha)\b"),
)
_SKU = re.compile(r"\b[a-z]{2,5}-\d{3,}\b")
_CONSULTA_ESTOQUE = re.compile(
    r"\b(tem|temos|ha)\b.*\b(peca|produto|camiseta|calca|sku)\b.*\b(loja|savassi|barra|ibirapuera)\b"
)
_AMBIGUA = re.compile(r"\b(essa|esta|aquela|esse|este|aquele)\s+(peca|produto|sku|pedido)\b")
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
        return ClassificacaoPergunta("esclarecer", "incompleta", False, ("pergunta_vazia",))

    requer_ferramenta = any(p.search(texto) for p in _PADROES_FERRAMENTA)
    requer_ferramenta = (
        requer_ferramenta or bool(_SKU.search(texto)) or bool(_CONSULTA_ESTOQUE.search(texto))
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
            "esclarecer", "incompleta", False, ("produto_ou_pedido_nao_identificado",)
        )

    complexa = bool(motivos)
    if requer_ferramenta:
        motivos.append("depende_de_dado_atual_ou_personalizado")
    if not complexa:
        motivos.append("consulta_direta_sem_risco_ou_analise")

    return ClassificacaoPergunta(
        "precisa" if complexa else "rapida",
        "complexa" if complexa else "simples",
        requer_ferramenta,
        tuple(motivos),
    )


def decidir_roteamento(
    pergunta: str,
    *,
    modelos_por_rota: Mapping[str, str | None],
    chaves_disponiveis: Mapping[Provedor, bool],
) -> PlanoRoteamento:
    """Seleciona destino configurado; nao faz fallback nem requisicao de rede."""
    classificacao = classificar_pergunta(pergunta)
    if classificacao.rota == "esclarecer":
        return PlanoRoteamento(classificacao, "esclarecer", None)

    configuracao = modelos_por_rota.get(classificacao.rota)
    if not configuracao:
        return PlanoRoteamento(classificacao, "modelo_nao_configurado", None)

    provedor_texto, separador, modelo = configuracao.partition(":")
    if not separador or not modelo.strip() or provedor_texto not in ("gemini", "groq"):
        return PlanoRoteamento(classificacao, "configuracao_invalida", None)

    provedor: Provedor = provedor_texto  # type: ignore[assignment]
    if not chaves_disponiveis.get(provedor, False):
        return PlanoRoteamento(classificacao, "provedor_sem_chave", None)

    return PlanoRoteamento(
        classificacao,
        "pronto",
        DestinoModelo(provedor=provedor, modelo=modelo.strip()),
    )


def planejar_pergunta(pergunta: str, configuracoes: Settings) -> PlanoRoteamento:
    """Monta o plano a partir da configuracao do servidor sem ler ou expor as chaves."""
    return decidir_roteamento(
        pergunta,
        modelos_por_rota={
            "rapida": configuracoes.assistente_modelo_rapido,
            "precisa": configuracoes.assistente_modelo_preciso,
        },
        chaves_disponiveis={
            "gemini": _chave_configurada(configuracoes.gemini_api_key),
            "groq": _chave_configurada(configuracoes.groq_api_key),
        },
    )


def _chave_configurada(chave: SecretStr | None) -> bool:
    return bool(chave and chave.get_secret_value().strip())
