"""Interface unica para os provedores de LLM do assistente (Groq e Gemini).

O fluxo do chatbot chama `responder(...)`; o provedor traduz o historico e as ferramentas para o
formato dele, faz as rodadas de chamada de ferramenta (cada uma executada pelo callback `executar`,
que valida e chama os services do backend) e devolve o texto final com o uso de tokens.

Seguranca: a chave so sai de `Settings` aqui dentro, vai no cabecalho (nunca na URL) e nao aparece
em log, excecao ou resposta. Erro do provedor vira `ErroProvedor` com o status HTTP e um motivo
curto, sem repetir o corpo da resposta. Nao ha fallback: quem escolhe o destino e o roteador.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.assistente.roteamento import DestinoModelo
from app.core.config import Settings

log = logging.getLogger(__name__)

TEMPO_LIMITE_SEGUNDOS = 30.0
URL_GROQ = "https://api.groq.com/openai/v1/chat/completions"
URL_GEMINI = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"


@dataclass(frozen=True)
class Ferramenta:
    nome: str
    descricao: str
    parametros: dict[str, Any]  # JSON Schema (type object)


@dataclass
class ChamadaFeita:
    nome: str
    argumentos: dict[str, Any]
    resultado: dict[str, Any]


@dataclass
class RespostaProvedor:
    texto: str
    chamadas: list[ChamadaFeita] = field(default_factory=list)
    tokens_entrada: int = 0
    tokens_saida: int = 0
    # False quando o modelo pediu mais rodadas de ferramenta do que o limite.
    concluida: bool = True


Executar = Callable[[str, dict[str, Any]], dict[str, Any]]


class ErroProvedor(RuntimeError):
    """`codigo` e o codigo de erro do provedor (ex.: rate_limit_exceeded), nunca o corpo inteiro."""

    def __init__(
        self, provedor: str, motivo: str, status: int | None = None, codigo: str | None = None
    ) -> None:
        self.provedor, self.motivo, self.status, self.codigo = provedor, motivo, status, codigo
        super().__init__(
            f"{provedor}: {motivo}"
            + (f" (HTTP {status})" if status else "")
            + (f" [{codigo}]" if codigo else "")
        )

    @property
    def limite_de_uso(self) -> bool:
        return self.status == 429


class Provedor(Protocol):
    def responder(
        self,
        *,
        modelo: str,
        sistema: str,
        historico: list[dict[str, str]],
        ferramentas: list[Ferramenta],
        executar: Executar,
        max_rodadas: int,
        max_tokens: int,
    ) -> RespostaProvedor: ...


_CLIENTE_HTTP: httpx.Client | None = None


def _cliente_http() -> httpx.Client:
    """Um cliente HTTP so para o processo: reaproveita as conexoes entre as mensagens."""
    global _CLIENTE_HTTP
    if _CLIENTE_HTTP is None:
        _CLIENTE_HTTP = httpx.Client(timeout=TEMPO_LIMITE_SEGUNDOS)
    return _CLIENTE_HTTP


# Limite por minuto do provedor (429): espera o que ele pedir, se for pouco, e tenta uma vez.
ESPERA_MAXIMA_SEGUNDOS = 6.0
_dormir = time.sleep


def _codigo_do_erro(resposta: httpx.Response) -> str | None:
    """So o codigo do erro (Groq: error.code; Gemini: error.status). A mensagem nao sai daqui."""
    try:
        erro = resposta.json().get("error")
    except (ValueError, AttributeError):
        return None
    if not isinstance(erro, dict):
        return None
    codigo = erro.get("code") or erro.get("status") or erro.get("type")
    return str(codigo)[:60] if codigo is not None else None


def _espera_pedida(resposta: httpx.Response) -> float:
    try:
        return float(resposta.headers.get("retry-after", "2"))
    except ValueError:
        return 2.0


def _postar(cliente: httpx.Client, provedor: str, url: str, cabecalhos: dict, corpo: dict) -> dict:
    for tentativa in range(2):
        try:
            resposta = cliente.post(
                url, headers=cabecalhos, json=corpo, timeout=TEMPO_LIMITE_SEGUNDOS
            )
        except httpx.TimeoutException as erro:
            raise ErroProvedor(provedor, "tempo esgotado") from erro
        except httpx.HTTPError as erro:
            raise ErroProvedor(provedor, "falha de conexao") from erro
        espera = _espera_pedida(resposta)
        if resposta.status_code == 429 and tentativa == 0 and espera <= ESPERA_MAXIMA_SEGUNDOS:
            _dormir(espera)
            continue
        break
    if resposta.is_error:
        # O corpo do erro nao e repetido: pode trazer detalhes da conta. So o codigo vai adiante.
        raise ErroProvedor(
            provedor,
            "resposta de erro do provedor",
            resposta.status_code,
            _codigo_do_erro(resposta),
        )
    try:
        dados = resposta.json()
    except ValueError as erro:
        raise ErroProvedor(provedor, "resposta ilegivel") from erro
    if not isinstance(dados, dict):
        raise ErroProvedor(provedor, "resposta ilegivel")
    return dados


def _inteiro(valor: Any) -> int:
    return valor if isinstance(valor, int) and valor >= 0 else 0


class ProvedorGroq:
    """API compativel com OpenAI (chat/completions com `tools`)."""

    nome = "groq"

    def __init__(self, chave: str, cliente: httpx.Client | None = None) -> None:
        self._chave = chave
        self._cliente = cliente or _cliente_http()

    def responder(
        self, *, modelo, sistema, historico, ferramentas, executar, max_rodadas, max_tokens
    ):
        mensagens: list[dict[str, Any]] = [{"role": "system", "content": sistema}] + [
            {"role": "user" if m["papel"] == "usuario" else "assistant", "content": m["texto"]}
            for m in historico
        ]
        declaracoes = [
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
        cabecalhos = {"Authorization": f"Bearer {self._chave}"}
        resposta = RespostaProvedor(texto="")
        for _ in range(max_rodadas + 1):
            dados = _postar(
                self._cliente,
                self.nome,
                URL_GROQ,
                cabecalhos,
                {
                    "model": modelo,
                    "messages": mensagens,
                    "tools": declaracoes,
                    "tool_choice": "auto",
                    "parallel_tool_calls": False,
                    "temperature": 0,
                    "max_tokens": max_tokens,
                },
            )
            uso = dados.get("usage") or {}
            resposta.tokens_entrada += _inteiro(uso.get("prompt_tokens"))
            resposta.tokens_saida += _inteiro(uso.get("completion_tokens"))
            escolhas = dados.get("choices") or [{}]
            mensagem = (escolhas[0] or {}).get("message") or {}
            chamadas = mensagem.get("tool_calls") or []
            if not chamadas:
                resposta.texto = mensagem.get("content") or ""
                return resposta
            if len(resposta.chamadas) + len(chamadas) > max_rodadas:
                break
            mensagens.append(mensagem)
            for item in chamadas:
                funcao = item.get("function") or {}
                try:
                    argumentos = json.loads(funcao.get("arguments") or "{}")
                except json.JSONDecodeError:
                    argumentos = {}
                if not isinstance(argumentos, dict):
                    argumentos = {}
                nome = str(funcao.get("name") or "")
                resultado = executar(nome, argumentos)
                resposta.chamadas.append(ChamadaFeita(nome, argumentos, resultado))
                mensagens.append(
                    {
                        "role": "tool",
                        "tool_call_id": item.get("id", ""),
                        "content": json.dumps(resultado, ensure_ascii=False, default=str),
                    }
                )
        resposta.concluida = False
        return resposta


def _esquema_gemini(esquema: dict[str, Any]) -> dict[str, Any]:
    """O Gemini usa o esquema OpenAPI dele: tipos em maiusculas e sem additionalProperties."""
    convertido: dict[str, Any] = {}
    for chave, valor in esquema.items():
        if chave == "additionalProperties":
            continue
        if chave == "type" and isinstance(valor, str):
            convertido[chave] = valor.upper()
        elif chave == "properties" and isinstance(valor, dict):
            convertido[chave] = {nome: _esquema_gemini(sub) for nome, sub in valor.items()}
        elif chave == "items" and isinstance(valor, dict):
            convertido[chave] = _esquema_gemini(valor)
        else:
            convertido[chave] = valor
    return convertido


class ProvedorGemini:
    """API generateContent com `functionDeclarations`."""

    nome = "gemini"

    def __init__(self, chave: str, cliente: httpx.Client | None = None) -> None:
        self._chave = chave
        self._cliente = cliente or _cliente_http()

    def responder(
        self, *, modelo, sistema, historico, ferramentas, executar, max_rodadas, max_tokens
    ):
        conteudos: list[dict[str, Any]] = [
            {
                "role": "user" if m["papel"] == "usuario" else "model",
                "parts": [{"text": m["texto"]}],
            }
            for m in historico
        ]
        corpo: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": sistema}]},
            "contents": conteudos,
            "tools": [
                {
                    "functionDeclarations": [
                        {
                            "name": f.nome,
                            "description": f.descricao,
                            "parameters": _esquema_gemini(f.parametros),
                        }
                        for f in ferramentas
                    ]
                }
            ],
            "generationConfig": {"temperature": 0, "maxOutputTokens": max_tokens},
        }
        # Chave no cabecalho, nao na URL (URL pode parar em log de proxy).
        cabecalhos = {"x-goog-api-key": self._chave}
        url = URL_GEMINI.format(modelo=modelo)
        resposta = RespostaProvedor(texto="")
        for _ in range(max_rodadas + 1):
            dados = _postar(self._cliente, self.nome, url, cabecalhos, corpo)
            uso = dados.get("usageMetadata") or {}
            resposta.tokens_entrada += _inteiro(uso.get("promptTokenCount"))
            resposta.tokens_saida += _inteiro(uso.get("candidatesTokenCount"))
            candidatos = dados.get("candidates") or [{}]
            conteudo = (candidatos[0] or {}).get("content") or {}
            partes = conteudo.get("parts") or []
            chamadas = [
                p["functionCall"] for p in partes if isinstance(p, dict) and "functionCall" in p
            ]
            if not chamadas:
                resposta.texto = "\n".join(
                    p["text"] for p in partes if isinstance(p, dict) and "text" in p
                )
                return resposta
            if len(resposta.chamadas) + len(chamadas) > max_rodadas:
                break
            conteudos.append(conteudo)
            retornos = []
            for chamada in chamadas:
                nome = str(chamada.get("name") or "")
                argumentos = chamada.get("args") if isinstance(chamada.get("args"), dict) else {}
                resultado = executar(nome, argumentos)
                resposta.chamadas.append(ChamadaFeita(nome, argumentos, resultado))
                retornos.append(
                    {
                        "functionResponse": {
                            "name": nome,
                            "response": json.loads(json.dumps(resultado, default=str)),
                        }
                    }
                )
            conteudos.append({"role": "user", "parts": retornos})
        resposta.concluida = False
        return resposta


def criar_provedor(destino: DestinoModelo, configuracoes: Settings) -> Provedor:
    """O provedor do destino escolhido pelo roteador. O roteador ja conferiu que a chave existe."""
    if destino.provedor == "groq" and configuracoes.groq_api_key:
        return ProvedorGroq(configuracoes.groq_api_key.get_secret_value())
    if destino.provedor == "gemini" and configuracoes.gemini_api_key:
        return ProvedorGemini(configuracoes.gemini_api_key.get_secret_value())
    raise ErroProvedor(destino.provedor, "chave ausente")
