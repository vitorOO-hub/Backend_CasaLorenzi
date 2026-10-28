"""Chamada aos provedores de LLM (Groq e Gemini) atras de uma interface unica.

Cada provedor conduz a troca de mensagens no formato dele, mas quem executa as ferramentas e o
servico do assistente (`executar`): o modelo so pede a ferramenta e os argumentos; a autorizacao e o
escopo ficam no backend. Os formatos seguem os do benchmark
(`scripts/benchmark_chatbot/run_tools.py`).

Seguranca: a chave vai so no cabecalho (nunca na URL, que aparece no log do httpx) e o corpo de
erro do provedor nunca e repassado nem registrado; so o status.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx

from app.assistente.roteamento import DestinoModelo
from app.core.config import Settings

registro = logging.getLogger("app.assistente")
# Trocado nos testes para nao esperar de verdade.
dormir = time.sleep

TIMEOUT_SEGUNDOS = 30.0
# No limite de uso (429), espera ate isto para tentar de novo uma vez; mais que isso, desiste.
ESPERA_MAXIMA_SEGUNDOS = 10.0
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"


@dataclass(frozen=True)
class Turno:
    autor: Literal["usuario", "assistente"]
    texto: str


@dataclass(frozen=True)
class Ferramenta:
    nome: str
    descricao: str
    # JSON Schema (type object) dos argumentos.
    parametros: dict[str, Any]


@dataclass
class ChamadaFeita:
    nome: str
    argumentos: dict[str, Any]
    resultado: dict[str, Any]


@dataclass
class Resultado:
    texto: str
    chamadas: list[ChamadaFeita] = field(default_factory=list)
    tokens_entrada: int = 0
    tokens_saida: int = 0
    # Verdadeiro quando o limite de rodadas de ferramenta acabou antes da resposta final.
    rodadas_esgotadas: bool = False


Executar = Callable[[str, dict[str, Any]], dict[str, Any]]


class ErroDoProvedor(Exception):
    """Falha de rede, timeout ou resposta de erro do provedor. Guarda so o status (e, no limite de
    uso, quantos segundos o provedor pediu para esperar)."""

    def __init__(self, provedor: str, status: int | None, espera: float | None = None) -> None:
        super().__init__(f"{provedor}: {status if status is not None else 'sem resposta'}")
        self.provedor = provedor
        self.status = status
        self.espera = espera


class Provedor(Protocol):
    def conversar(
        self,
        modelo: str,
        sistema: str,
        historico: Sequence[Turno],
        ferramentas: Sequence[Ferramenta],
        executar: Executar,
        *,
        max_rodadas: int,
        max_tokens: int,
    ) -> Resultado: ...


def _argumentos(valor: Any) -> dict[str, Any]:
    if isinstance(valor, str):
        try:
            valor = json.loads(valor or "{}")
        except json.JSONDecodeError:
            return {}
    return valor if isinstance(valor, dict) else {}


def _espera_pedida(resposta: httpx.Response) -> float | None:
    """Segundos que o provedor pediu no limite de uso: cabecalho Retry-After (Groq) ou o
    `retryDelay` do erro (Gemini). Le so esse numero; o resto do corpo nao e usado."""
    cabecalho = resposta.headers.get("retry-after")
    if cabecalho:
        try:
            return max(float(cabecalho), 0.0)
        except ValueError:
            pass
    try:
        detalhes = (resposta.json().get("error") or {}).get("details") or []
    except (ValueError, AttributeError):
        return None
    for detalhe in detalhes:
        atraso = str(detalhe.get("retryDelay", "")) if isinstance(detalhe, dict) else ""
        if atraso.endswith("s"):
            try:
                return max(float(atraso[:-1]), 0.0)
            except ValueError:
                return None
    return None


def _inteiro(valor: Any) -> int:
    return valor if isinstance(valor, int) and valor >= 0 else 0


class _ClienteHttp:
    def __init__(self, nome: str, cliente: httpx.Client | None) -> None:
        self.nome = nome
        self.cliente = cliente or httpx.Client(timeout=TIMEOUT_SEGUNDOS)

    def postar(self, url: str, cabecalhos: dict[str, str], corpo: dict[str, Any]) -> dict[str, Any]:
        for tentativa in range(2):
            try:
                resposta = self.cliente.post(url, headers=cabecalhos, json=corpo)
            except httpx.HTTPError as erro:
                registro.warning("provedor %s sem resposta (%s)", self.nome, type(erro).__name__)
                raise ErroDoProvedor(self.nome, None) from None
            if resposta.status_code != 429:
                break
            # Limite de uso por minuto: espera o que o provedor pediu, uma vez, se for curto.
            espera = _espera_pedida(resposta)
            registro.warning("provedor %s no limite de uso (espera %s s)", self.nome, espera)
            if tentativa or espera is None or espera > ESPERA_MAXIMA_SEGUNDOS:
                raise ErroDoProvedor(self.nome, 429, espera)
            dormir(espera + 0.2)
        if resposta.is_error:
            registro.warning("provedor %s respondeu %s", self.nome, resposta.status_code)
            raise ErroDoProvedor(self.nome, resposta.status_code)
        try:
            dados = resposta.json()
        except ValueError:
            raise ErroDoProvedor(self.nome, resposta.status_code) from None
        return dados if isinstance(dados, dict) else {}


class ProvedorGroq:
    """API compativel com a da OpenAI (chat completions com tools)."""

    def __init__(self, chave: str, cliente: httpx.Client | None = None) -> None:
        self._chave = chave
        self._http = _ClienteHttp("groq", cliente)

    def conversar(
        self, modelo, sistema, historico, ferramentas, executar, *, max_rodadas, max_tokens
    ):
        mensagens: list[dict[str, Any]] = [{"role": "system", "content": sistema}]
        mensagens += [
            {"role": "user" if t.autor == "usuario" else "assistant", "content": t.texto}
            for t in historico
        ]
        resultado = Resultado(texto="")
        especificacao = [
            {
                "type": "function",
                "function": {
                    "name": f.nome,
                    "description": f.descricao,
                    "parameters": f.parametros,
                },
            }
            for f in ferramentas
        ]
        for _ in range(max_rodadas + 1):
            corpo: dict[str, Any] = {
                "model": modelo,
                "messages": mensagens,
                "temperature": 0.2,
                "max_completion_tokens": max_tokens,
            }
            if especificacao:
                corpo |= {
                    "tools": especificacao,
                    "tool_choice": "auto",
                    "parallel_tool_calls": False,
                }
            dados = self._http.postar(GROQ_URL, {"Authorization": f"Bearer {self._chave}"}, corpo)
            uso = dados.get("usage") or {}
            resultado.tokens_entrada += _inteiro(uso.get("prompt_tokens"))
            resultado.tokens_saida += _inteiro(uso.get("completion_tokens"))
            mensagem = ((dados.get("choices") or [{}])[0] or {}).get("message") or {}
            chamadas = mensagem.get("tool_calls") or []
            if not chamadas:
                resultado.texto = (mensagem.get("content") or "").strip()
                return resultado
            if len(resultado.chamadas) + len(chamadas) > max_rodadas:
                break
            mensagens.append(
                {
                    "role": "assistant",
                    "content": mensagem.get("content") or "",
                    "tool_calls": chamadas,
                }
            )
            for chamada in chamadas:
                funcao = chamada.get("function") or {}
                nome, argumentos = str(funcao.get("name", "")), _argumentos(funcao.get("arguments"))
                saida = executar(nome, argumentos)
                resultado.chamadas.append(ChamadaFeita(nome, argumentos, saida))
                mensagens.append(
                    {
                        "role": "tool",
                        "tool_call_id": chamada.get("id", ""),
                        "content": json.dumps(saida, ensure_ascii=False, default=str),
                    }
                )
        resultado.rodadas_esgotadas = True
        return resultado


def _schema_gemini(parametros: dict[str, Any]) -> dict[str, Any]:
    """O Gemini nao aceita `additionalProperties` e usa os tipos em maiusculas."""
    schema = json.loads(json.dumps(parametros))
    schema.pop("additionalProperties", None)
    for valor in [schema, *schema.get("properties", {}).values()]:
        if isinstance(valor.get("type"), str):
            valor["type"] = valor["type"].upper()
    return schema


class ProvedorGemini:
    def __init__(self, chave: str, cliente: httpx.Client | None = None) -> None:
        self._chave = chave
        self._http = _ClienteHttp("gemini", cliente)

    def conversar(
        self, modelo, sistema, historico, ferramentas, executar, *, max_rodadas, max_tokens
    ):
        conteudos: list[dict[str, Any]] = [
            {"role": "user" if t.autor == "usuario" else "model", "parts": [{"text": t.texto}]}
            for t in historico
        ]
        corpo: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": sistema}]},
            "contents": conteudos,
            # O orcamento inclui o raciocinio interno dos modelos que pensam antes de responder.
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": max_tokens * 2},
        }
        if ferramentas:
            corpo["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": f.nome,
                            "description": f.descricao,
                            "parameters": _schema_gemini(f.parametros),
                        }
                        for f in ferramentas
                    ]
                }
            ]
        url = GEMINI_URL.format(modelo=modelo)
        resultado = Resultado(texto="")
        for _ in range(max_rodadas + 1):
            dados = self._http.postar(url, {"x-goog-api-key": self._chave}, corpo)
            uso = dados.get("usageMetadata") or {}
            resultado.tokens_entrada += _inteiro(uso.get("promptTokenCount"))
            resultado.tokens_saida += _inteiro(uso.get("candidatesTokenCount"))
            conteudo = ((dados.get("candidates") or [{}])[0] or {}).get("content") or {}
            partes = conteudo.get("parts") or []
            pedidos = [p["functionCall"] for p in partes if isinstance(p.get("functionCall"), dict)]
            if not pedidos:
                textos = [p["text"] for p in partes if "text" in p and not p.get("thought")]
                resultado.texto = "\n".join(textos).strip()
                return resultado
            if len(resultado.chamadas) + len(pedidos) > max_rodadas:
                break
            # O conteudo volta inteiro: os modelos novos exigem a assinatura da chamada de volta.
            conteudos.append(conteudo)
            respostas = []
            for pedido in pedidos:
                nome, argumentos = str(pedido.get("name", "")), _argumentos(pedido.get("args"))
                saida = executar(nome, argumentos)
                resultado.chamadas.append(ChamadaFeita(nome, argumentos, saida))
                respostas.append({"functionResponse": {"name": nome, "response": saida}})
            conteudos.append({"role": "user", "parts": respostas})
        resultado.rodadas_esgotadas = True
        return resultado


def provedor_para(destino: DestinoModelo, configuracoes: Settings) -> Provedor:
    """O destino ja passou pelo roteador (`estado == "pronto"`): a chave existe."""
    if destino.provedor == "groq":
        chave = configuracoes.groq_api_key
        return ProvedorGroq(chave.get_secret_value() if chave else "")
    chave = configuracoes.gemini_api_key
    return ProvedorGemini(chave.get_secret_value() if chave else "")
