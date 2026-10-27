from __future__ import annotations

import argparse
import csv
import json
import os
import re
import statistics
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = Path(__file__).with_name("casos.json")
TIMEOUT_SECONDS = 60.0


class APIRequestError(RuntimeError):
    def __init__(self, status_code: int, error_body: dict[str, Any]):
        self.status_code = status_code
        details = error_body.get("error", error_body)
        if not isinstance(details, dict):
            details = {}
        code = " ".join(
            str(details.get(key, "")) for key in ("code", "type", "message")
        ).casefold()
        stop_terms = ("billing", "credit", "quota", "spend", "resource_exhausted")
        self.stop_run = status_code in (402, 429) or any(term in code for term in stop_terms)
        self.label = f"HTTP {status_code}"
        error_type = details.get("status") or details.get("type") or details.get("code")
        message = " ".join(str(details.get("message", "")).split())
        message = re.sub(r"AIza[\w-]{20,}", "[REDACTED_API_KEY]", message)
        message = re.sub(r"(?i)(key=)[^&\s\"']+", r"\1[REDACTED]", message)
        if error_type:
            self.label += f" {str(error_type)[:80]}"
        if message:
            self.label += f": {message[:240]}"
        if self.stop_run:
            self.label += " (billing/quota; interrompido)"
        super().__init__(self.label)


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in value if not unicodedata.combining(char))


def request_json(
    client: httpx.Client,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
) -> dict[str, Any]:
    response = client.post(url, headers=headers, json=payload)
    if response.is_error:
        try:
            error_body = response.json()
        except ValueError:
            error_body = {}
        raise APIRequestError(response.status_code, error_body)
    return response.json()


def ask_gemini(
    client: httpx.Client, model: str, key: str, system: str, prompt: str
) -> tuple[str, int | None, int | None]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0},
    }
    data = request_json(client, f"{url}?key={key}", {}, payload)
    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    text = "\n".join(part["text"] for part in parts if "text" in part)
    usage = data.get("usageMetadata", {})
    return text, usage.get("promptTokenCount"), usage.get("candidatesTokenCount")


def ask_groq(
    client: httpx.Client, model: str, key: str, system: str, prompt: str
) -> tuple[str, int | None, int | None]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
    }
    data = request_json(
        client,
        "https://api.groq.com/openai/v1/chat/completions",
        {"Authorization": f"Bearer {key}"},
        payload,
    )
    usage = data.get("usage", {})
    text = data.get("choices", [{}])[0].get("message", {}).get("content") or ""
    return text, usage.get("prompt_tokens"), usage.get("completion_tokens")


def ask_anthropic(
    client: httpx.Client, model: str, key: str, system: str, prompt: str
) -> tuple[str, int | None, int | None]:
    payload = {
        "model": model,
        "max_tokens": 300,
        "temperature": 0,
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
    }
    data = request_json(
        client,
        "https://api.anthropic.com/v1/messages",
        {"x-api-key": key, "anthropic-version": "2023-06-01"},
        payload,
    )
    text = "\n".join(
        block["text"] for block in data.get("content", []) if block.get("type") == "text"
    )
    usage = data.get("usage", {})
    return text, usage.get("input_tokens"), usage.get("output_tokens")


PROVIDERS = (
    ("gemini", "GEMINI_API_KEY", "BENCH_GEMINI_MODEL", ask_gemini),
    ("gemma", "GEMINI_API_KEY", "BENCH_GEMMA_MODEL", ask_gemini),
    ("groq", "GROQ_API_KEY", "BENCH_GROQ_MODEL", ask_groq),
    ("anthropic", "ANTHROPIC_API_KEY", "BENCH_ANTHROPIC_MODEL", ask_anthropic),
)


def estimate_cost(provider: str, input_tokens: int | None, output_tokens: int | None) -> str:
    prefix = f"BENCH_{provider.upper()}"
    input_rate = os.getenv(f"{prefix}_INPUT_USD_PER_MILLION", "").strip()
    output_rate = os.getenv(f"{prefix}_OUTPUT_USD_PER_MILLION", "").strip()
    if not input_rate or not output_rate or input_tokens is None or output_tokens is None:
        return ""
    try:
        cost = input_tokens * float(input_rate) + output_tokens * float(output_rate)
    except ValueError:
        return ""
    return f"{cost / 1_000_000:.10f}"


def score(text: str, case: dict[str, Any]) -> tuple[bool, str]:
    normalized = normalize(text)
    missing = [
        item for item in case["deve_conter"] if normalize(item) not in normalized
    ]
    forbidden = [
        item for item in case["nao_deve_conter"] if normalize(item) in normalized
    ]
    details = []
    if missing:
        details.append(f"faltou: {', '.join(missing)}")
    if forbidden:
        details.append(f"indevido: {', '.join(forbidden)}")
    return not missing and not forbidden, "; ".join(details)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compara APIs com casos ficticios.")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument(
        "--providers",
        nargs="+",
        choices=["gemini", "gemma", "groq", "anthropic"],
        default=["gemini", "gemma"],
        help="Modelos incluidos (padrao: Gemini e Gemma).",
    )
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("--repetitions precisa ser pelo menos 1")

    load_dotenv(ROOT / ".env")
    settings = []
    missing = []
    for provider, key_name, model_name, call in PROVIDERS:
        if provider not in args.providers:
            continue
        key = os.getenv(key_name, "").strip()
        model = os.getenv(model_name, "").strip()
        if not key:
            missing.append(key_name)
        if not model:
            missing.append(model_name)
        settings.append((provider, key, model, call))
    if missing:
        print("Configure no .env local: " + ", ".join(missing))
        return 2

    dataset = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    system = (
        "Voce e um assistente de atendimento. Responda em portugues, de forma breve, "
        "usando exclusivamente os dados fornecidos. Nao invente. Se faltarem dados, "
        "diga isso claramente. Nunca revele nem invente dados pessoais ou financeiros. "
        "Quando a pergunta estiver ambigua, peca esclarecimento."
    )
    run_at = datetime.now().astimezone()
    run_id = run_at.strftime("%Y%m%d-%H%M%S-%f")
    output_path = Path(__file__).with_name("resultados") / f"baseline-{run_id}.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "run_id",
        "run_timestamp",
        "provider",
        "model",
        "case_id",
        "repetition",
        "passed_auto_check",
        "check_details",
        "latency_ms",
        "input_tokens",
        "output_tokens",
        "estimated_cost_usd",
        "answer",
        "error",
    ]

    with httpx.Client(timeout=TIMEOUT_SECONDS) as client, output_path.open(
        "w", newline="", encoding="utf-8-sig"
    ) as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fields)
        writer.writeheader()
        summary = {
            provider: {
                "latencies": [],
                "passed": 0,
                "total": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "estimated_cost_usd": 0.0,
                "has_cost": True,
            }
            for provider, _, _, _ in settings
        }
        stop_reason = ""
        for case in dataset["casos"]:
            prompt = (
                f"Dados ficticios para esta conversa:\n{dataset['contexto']}\n\n"
                f"Pergunta: {case['pergunta']}"
            )
            for provider, key, model, call in settings:
                for repetition in range(1, args.repetitions + 1):
                    started = time.perf_counter()
                    try:
                        answer, input_tokens, output_tokens = call(
                            client, model, key, system, prompt
                        )
                        passed, details = score(answer, case)
                        error = ""
                    except Exception as exc:
                        answer, input_tokens, output_tokens = "", "", ""
                        passed, details = False, ""
                        error = (
                            exc.label
                            if isinstance(exc, APIRequestError)
                            else type(exc).__name__
                        )
                        if isinstance(exc, APIRequestError) and exc.stop_run:
                            stop_reason = exc.label
                    elapsed_ms = round((time.perf_counter() - started) * 1000)
                    provider_summary = summary[provider]
                    provider_summary["latencies"].append(elapsed_ms)
                    provider_summary["total"] += 1
                    provider_summary["passed"] += int(passed)
                    if isinstance(input_tokens, int):
                        provider_summary["input_tokens"] += input_tokens
                    if isinstance(output_tokens, int):
                        provider_summary["output_tokens"] += output_tokens
                    estimated_cost = estimate_cost(
                        provider, input_tokens, output_tokens
                    )
                    if estimated_cost:
                        provider_summary["estimated_cost_usd"] += float(estimated_cost)
                    else:
                        provider_summary["has_cost"] = False
                    writer.writerow(
                        {
                            "run_id": run_id,
                            "run_timestamp": run_at.isoformat(timespec="seconds"),
                            "provider": provider,
                            "model": model,
                            "case_id": case["id"],
                            "repetition": repetition,
                            "passed_auto_check": passed,
                            "check_details": details,
                            "latency_ms": elapsed_ms,
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                            "estimated_cost_usd": estimated_cost,
                            "answer": answer.replace("\n", " ").strip(),
                            "error": error,
                        }
                    )
                    output_file.flush()
                    print(
                        f"{provider} | {case['id']} | rodada {repetition} | "
                        f"{elapsed_ms} ms | {'OK' if passed else 'REVISAR'}"
                    )
                    if stop_reason:
                        print(f"Parando novas chamadas: {stop_reason}")
                        break
                if stop_reason:
                    break
            if stop_reason:
                break

    print("\nResumo do piloto (a taxa automatica e heuristica):")
    for provider, values in summary.items():
        if not values["total"]:
            print(f"{provider}: nao testado")
            continue
        accuracy = 100 * values["passed"] / values["total"]
        median_ms = statistics.median(values["latencies"])
        cost = (
            f"US$ {values['estimated_cost_usd']:.6f}"
            if values["has_cost"]
            else "tarifas nao configuradas"
        )
        print(
            f"{provider}: acerto {accuracy:.1f}% | mediana {median_ms:.0f} ms | "
            f"tokens {values['input_tokens']} entrada / {values['output_tokens']} saida | "
            f"custo {cost}"
        )
    print(f"\nResultados: {output_path}")
    print("A checagem automatica e indicativa; revisem as respostas antes de concluir.")
    return 1 if stop_reason else 0


if __name__ == "__main__":
    raise SystemExit(main())
