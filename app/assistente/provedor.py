"""Adaptadores HTTP de tool calling para Gemini e Groq."""

import json
import logging
import re
from typing import Any
from uuid import uuid4

import httpx

from app.assistente.roteamento import DestinoModelo
from app.core.config import Settings

TIMEOUT_GROQ_SEGUNDOS = 25.0
TIMEOUT_GEMINI_SEGUNDOS = 60.0
MAX_TOKENS_SAIDA = 500
logger = logging.getLogger(__name__)


class FalhaDoProvedor(Exception):
    """Falha externa sem carregar chave, URL sensivel ou corpo do provedor."""


def _detalhe_http_seguro(resposta: httpx.Response, chave: str) -> tuple[str, str]:
    """Extrai apenas o status e a mensagem curta do erro, nunca o corpo completo."""
    try:
        erro = resposta.json().get("error", {})
    except (ValueError, AttributeError):
        erro = {}
    if not isinstance(erro, dict):
        erro = {}

    status = erro.get("status")
    mensagem = erro.get("message")
    status = status if isinstance(status, str) else "desconhecido"
    if not isinstance(mensagem, str):
        mensagem = "mensagem de erro indisponível"
    mensagem = mensagem.replace(chave, "[chave omitida]")
    mensagem = re.sub(r"AIza[0-9A-Za-z_-]{20,}", "[chave omitida]", mensagem)
    mensagem = re.sub(r"[\r\n\t]+", " ", mensagem).strip()
    return status[:80], mensagem[:500]


def _tools_groq(ferramentas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": item["name"],
                "description": item["description"],
                "parameters": item["parameters"],
            },
        }
        for item in ferramentas
    ]


def _historico_groq(historico: list[dict[str, Any]]) -> list[dict[str, Any]]:
    resultado: list[dict[str, Any]] = []
    for mensagem in historico:
        if mensagem["role"] == "assistant" and mensagem.get("tool_calls"):
            resultado.append(
                {
                    "role": "assistant",
                    "content": mensagem.get("content") or None,
                    "tool_calls": [
                        {
                            "id": chamada["id"],
                            "type": "function",
                            "function": {
                                "name": chamada["name"],
                                "arguments": json.dumps(chamada["arguments"], ensure_ascii=False),
                            },
                        }
                        for chamada in mensagem["tool_calls"]
                    ],
                }
            )
        elif mensagem["role"] == "tool":
            resultado.append(
                {
                    "role": "tool",
                    "tool_call_id": mensagem["tool_call_id"],
                    "content": mensagem["content"],
                }
            )
        else:
            resultado.append({"role": mensagem["role"], "content": mensagem["content"]})
    return resultado


def _tools_gemini(ferramentas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "functionDeclarations": [
                {
                    "name": item["name"],
                    "description": item["description"],
                    "parametersJsonSchema": item["parameters"],
                }
                for item in ferramentas
            ]
        }
    ]


def _historico_gemini(historico: list[dict[str, Any]]) -> list[dict[str, Any]]:
    resultado: list[dict[str, Any]] = []
    for mensagem in historico:
        if mensagem["role"] == "tool":
            try:
                resposta = json.loads(mensagem["content"])
            except (TypeError, json.JSONDecodeError):
                resposta = {"erro": "resultado indisponivel"}
            resultado.append(
                {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": mensagem["name"],
                                "response": resposta,
                            }
                        }
                    ],
                }
            )
        elif mensagem["role"] == "assistant" and mensagem.get("tool_calls"):
            partes = []
            for chamada in mensagem["tool_calls"]:
                parte = {
                    "functionCall": {
                        "name": chamada["name"],
                        "args": chamada["arguments"],
                    }
                }
                assinatura = chamada.get("thought_signature")
                if assinatura:
                    parte["thoughtSignature"] = assinatura
                partes.append(parte)
            resultado.append({"role": "model", "parts": partes})
        else:
            resultado.append(
                {
                    "role": "model" if mensagem["role"] == "assistant" else "user",
                    "parts": [{"text": mensagem["content"]}],
                }
            )
    return resultado


def completar(
    destino: DestinoModelo,
    configuracoes: Settings,
    sistema: str,
    historico: list[dict[str, Any]],
    ferramentas: list[dict[str, Any]],
) -> dict[str, Any]:
    provedor = destino.provedor
    secret = configuracoes.groq_api_key if provedor == "groq" else configuracoes.gemini_api_key
    chave = secret.get_secret_value().strip() if secret else ""
    if not chave:
        raise FalhaDoProvedor("Provedor sem chave configurada")
    try:
        timeout = TIMEOUT_GROQ_SEGUNDOS if provedor == "groq" else TIMEOUT_GEMINI_SEGUNDOS
        with httpx.Client(timeout=timeout) as cliente:
            if provedor == "groq":
                resposta = cliente.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {chave}"},
                    json={
                        "model": destino.modelo,
                        "messages": [
                            {"role": "system", "content": sistema},
                            *_historico_groq(historico),
                        ],
                        "tools": _tools_groq(ferramentas),
                        "tool_choice": "auto",
                        "parallel_tool_calls": False,
                        "temperature": 0,
                        "max_tokens": MAX_TOKENS_SAIDA,
                    },
                )
                resposta.raise_for_status()
                dados = resposta.json()
                escolha = dados["choices"][0]["message"]
                chamadas = []
                for chamada in escolha.get("tool_calls", []):
                    funcao = chamada.get("function", {})
                    try:
                        argumentos = json.loads(funcao.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        argumentos = {}
                    chamadas.append(
                        {
                            "id": chamada.get("id") or str(uuid4()),
                            "name": funcao.get("name", ""),
                            "arguments": argumentos if isinstance(argumentos, dict) else {},
                        }
                    )
                return {
                    "texto": escolha.get("content") or "",
                    "chamadas": chamadas,
                    "tokens_entrada": int(dados.get("usage", {}).get("prompt_tokens", 0)),
                    "tokens_saida": int(dados.get("usage", {}).get("completion_tokens", 0)),
                }

            url = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{destino.modelo}:generateContent"
            )
            resposta = cliente.post(
                url,
                params={"key": chave},
                json={
                    "systemInstruction": {"parts": [{"text": sistema}]},
                    "contents": _historico_gemini(historico),
                    "tools": _tools_gemini(ferramentas),
                    "toolConfig": {"functionCallingConfig": {"mode": "AUTO"}},
                    "generationConfig": {"temperature": 0, "maxOutputTokens": MAX_TOKENS_SAIDA},
                },
            )
            resposta.raise_for_status()
            dados = resposta.json()
            partes = dados["candidates"][0]["content"]["parts"]
            chamadas = [
                {
                    "id": str(uuid4()),
                    "name": parte["functionCall"].get("name", ""),
                    "arguments": parte["functionCall"].get("args", {}),
                    "thought_signature": parte.get("thoughtSignature")
                    or parte.get("thought_signature"),
                }
                for parte in partes
                if "functionCall" in parte
            ]
            uso = dados.get("usageMetadata", {})
            return {
                "texto": "\n".join(p["text"] for p in partes if "text" in p),
                "chamadas": chamadas,
                "tokens_entrada": int(uso.get("promptTokenCount", 0)),
                "tokens_saida": int(uso.get("candidatesTokenCount", 0)),
            }
    except httpx.HTTPStatusError as erro:
        status_provedor, mensagem = _detalhe_http_seguro(erro.response, chave)
        logger.warning(
            "Provedor %s rejeitou a chamada (http_status=%s, provider_status=%s, message=%s)",
            provedor,
            erro.response.status_code,
            status_provedor,
            mensagem,
        )
        raise FalhaDoProvedor("Nao foi possivel consultar o provedor de IA") from None
    except httpx.HTTPError as erro:
        logger.warning(
            "Falha de transporte com provedor %s (tipo=%s)", provedor, type(erro).__name__
        )
        raise FalhaDoProvedor("Nao foi possivel consultar o provedor de IA") from None
    except (KeyError, IndexError, TypeError, ValueError) as erro:
        logger.warning(
            "Resposta incompatível do provedor %s (tipo=%s)", provedor, type(erro).__name__
        )
        raise FalhaDoProvedor("Nao foi possivel consultar o provedor de IA") from None
