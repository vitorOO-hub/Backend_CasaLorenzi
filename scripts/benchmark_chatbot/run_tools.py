from __future__ import annotations

import argparse
import csv
import json
import os
import re
import statistics
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from fixtures import TOOL_DECLARATIONS, run_tool, score_tool_calls
from run import CASES_PATH, PROVIDERS, ROOT, estimate_cost, score

MAX_TOOL_ROUNDS = 4
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


def add_usage(
    total: dict[str, int],
    usage: dict[str, Any],
    input_key: str,
    output_key: str,
) -> None:
    input_tokens = usage.get(input_key)
    output_tokens = usage.get(output_key)
    if isinstance(input_tokens, int):
        total["input"] += input_tokens
    if isinstance(output_tokens, int):
        total["output"] += output_tokens


def post_json(
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


def tool_spec(provider: str) -> list[dict[str, Any]]:
    if provider in {"gemini", "gemma"}:
        declarations = []
        for item in TOOL_DECLARATIONS:
            schema = json.loads(json.dumps(item["parameters"]))
            for value in [schema, *schema.get("properties", {}).values()]:
                value["type"] = value["type"].upper()
            schema.pop("additionalProperties", None)
            declarations.append({**item, "parameters": schema})
        return [{"functionDeclarations": declarations}]
    if provider == "groq":
        return [
            {
                "type": "function",
                "function": {
                    "name": item["name"],
                    "description": item["description"],
                    "parameters": item["parameters"],
                },
            }
            for item in TOOL_DECLARATIONS
        ]
    return [
        {
            "name": item["name"],
            "description": item["description"],
            "input_schema": item["parameters"],
        }
        for item in TOOL_DECLARATIONS
    ]


def call_gemini(
    client: httpx.Client, model: str, key: str, system: str, prompt: str
) -> tuple[str, list[dict[str, Any]], int, int]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload: dict[str, Any] = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "tools": tool_spec("gemini"),
        "generationConfig": {"temperature": 0},
    }
    calls: list[dict[str, Any]] = []
    usage = {"input": 0, "output": 0}
    for _ in range(MAX_TOOL_ROUNDS + 1):
        data = post_json(client, f"{url}?key={key}", {}, payload)
        add_usage(usage, data.get("usageMetadata", {}), "promptTokenCount", "candidatesTokenCount")
        candidate = data.get("candidates", [{}])[0]
        content = candidate.get("content", {})
        parts = content.get("parts", [])
        function_calls = [part["functionCall"] for part in parts if "functionCall" in part]
        if not function_calls:
            answer = "\n".join(part["text"] for part in parts if "text" in part)
            return answer, calls, usage["input"], usage["output"]
        if len(calls) + len(function_calls) > MAX_TOOL_ROUNDS:
            break
        payload["contents"].append(content)
        responses = []
        for function_call in function_calls:
            name = function_call.get("name", "")
            arguments = function_call.get("args", {})
            if not isinstance(arguments, dict):
                arguments = {}
            calls.append({"nome": name, "argumentos": arguments})
            responses.append(
                {
                    "functionResponse": {
                        "name": name,
                        "response": run_tool(name, arguments),
                    }
                }
            )
        payload["contents"].append({"role": "user", "parts": responses})
    return "Nao foi possivel concluir a consulta simulada.", calls, usage["input"], usage["output"]


def call_groq(
    client: httpx.Client, model: str, key: str, system: str, prompt: str
) -> tuple[str, list[dict[str, Any]], int, int]:
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {key}"}
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]
    calls: list[dict[str, Any]] = []
    usage = {"input": 0, "output": 0}
    for _ in range(MAX_TOOL_ROUNDS + 1):
        data = post_json(
            client,
            url,
            headers,
            {
                "model": model,
                "messages": messages,
                "tools": tool_spec("groq"),
                "tool_choice": "auto",
                "parallel_tool_calls": False,
                "temperature": 0,
            },
        )
        add_usage(usage, data.get("usage", {}), "prompt_tokens", "completion_tokens")
        message = data.get("choices", [{}])[0].get("message", {})
        tool_calls = message.get("tool_calls", [])
        if not tool_calls:
            return (
                message.get("content") or "",
                calls,
                usage["input"],
                usage["output"],
            )
        if len(calls) + len(tool_calls) > MAX_TOOL_ROUNDS:
            break
        messages.append(message)
        for item in tool_calls:
            function = item.get("function", {})
            try:
                arguments = json.loads(function.get("arguments", "{}"))
            except json.JSONDecodeError:
                arguments = {}
            if not isinstance(arguments, dict):
                arguments = {}
            name = function.get("name", "")
            calls.append({"nome": name, "argumentos": arguments})
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": item["id"],
                    "content": json.dumps(
                        run_tool(name, arguments), ensure_ascii=False
                    ),
                }
            )
    return "Nao foi possivel concluir a consulta simulada.", calls, usage["input"], usage["output"]


def call_anthropic(
    client: httpx.Client, model: str, key: str, system: str, prompt: str
) -> tuple[str, list[dict[str, Any]], int, int]:
    url = "https://api.anthropic.com/v1/messages"
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    calls: list[dict[str, Any]] = []
    usage = {"input": 0, "output": 0}
    for _ in range(MAX_TOOL_ROUNDS + 1):
        data = post_json(
            client,
            url,
            headers,
            {
                "model": model,
                "max_tokens": 400,
                "temperature": 0,
                "system": system,
                "messages": messages,
                "tools": tool_spec("anthropic"),
                "tool_choice": {"type": "auto", "disable_parallel_tool_use": True},
            },
        )
        add_usage(usage, data.get("usage", {}), "input_tokens", "output_tokens")
        content = data.get("content", [])
        tool_uses = [item for item in content if item.get("type") == "tool_use"]
        if not tool_uses:
            answer = "\n".join(item["text"] for item in content if item.get("type") == "text")
            return answer, calls, usage["input"], usage["output"]
        if len(calls) + len(tool_uses) > MAX_TOOL_ROUNDS:
            break
        messages.append({"role": "assistant", "content": content})
        results = []
        for item in tool_uses:
            arguments = item.get("input", {})
            if not isinstance(arguments, dict):
                arguments = {}
            name = item.get("name", "")
            calls.append({"nome": name, "argumentos": arguments})
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": item["id"],
                    "content": json.dumps(run_tool(name, arguments), ensure_ascii=False),
                }
            )
        messages.append({"role": "user", "content": results})
    return "Nao foi possivel concluir a consulta simulada.", calls, usage["input"], usage["output"]


TOOL_CALLS = {
    "gemini": call_gemini,
    "gemma": call_gemini,
    "groq": call_groq,
    "anthropic": call_anthropic,
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compara chamada de ferramentas em APIs com fixtures ficticias."
    )
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument(
        "--case",
        help="Executa apenas um caso (consulte os ids em casos.json).",
    )
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
    for provider, key_name, model_name, _ in PROVIDERS:
        if provider not in args.providers:
            continue
        key = os.getenv(key_name, "").strip()
        model = os.getenv(model_name, "").strip()
        if not key:
            missing.append(key_name)
        if not model:
            missing.append(model_name)
        settings.append((provider, key, model, TOOL_CALLS[provider]))
    if missing:
        print("Configure no .env local: " + ", ".join(missing))
        return 2

    dataset = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    cases = dataset["casos"]
    if args.case:
        cases = [case for case in cases if case["id"] == args.case]
        if not cases:
            parser.error(f"caso desconhecido: {args.case}")
    system = (
        "Voce e um assistente de atendimento. Responda em portugues, brevemente. "
        "Use as ferramentas para consultar dados, sem inventar. Se faltar identificacao, "
        "peca esclarecimento. Nunca revele nem invente dados pessoais ou financeiros. "
        "Apenas as referencias de cliente ficticias fornecidas podem ser usadas."
    )
    run_at = datetime.now().astimezone()
    run_id = run_at.strftime("%Y%m%d-%H%M%S-%f")
    output_path = Path(__file__).with_name("resultados") / f"ferramentas-{run_id}.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "run_id", "run_timestamp",
        "provider", "model", "case_id", "repetition", "tool_calls_passed",
        "tool_check_details", "answer_passed_auto_check", "answer_check_details",
        "latency_ms", "input_tokens", "output_tokens", "estimated_cost_usd",
        "tool_calls", "answer", "error",
    ]
    summary = {
        provider: {"latencies": [], "tools_passed": 0, "answers_passed": 0, "total": 0}
        for provider, _, _, _ in settings
    }
    with httpx.Client(timeout=TIMEOUT_SECONDS) as client, output_path.open(
        "w", newline="", encoding="utf-8-sig"
    ) as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fields)
        writer.writeheader()
        stop_reason = ""
        for case in cases:
            for provider, key, model, call in settings:
                for repetition in range(1, args.repetitions + 1):
                    started = time.perf_counter()
                    try:
                        answer, actual_calls, input_tokens, output_tokens = call(
                            client, model, key, system, case["pergunta"]
                        )
                        tools_passed, tool_details = score_tool_calls(
                            actual_calls, case["espera_ferramentas"]
                        )
                        answer_passed, answer_details = score(answer, case)
                        error = ""
                    except Exception as exc:
                        answer, actual_calls, input_tokens, output_tokens = "", [], "", ""
                        tools_passed, answer_passed = False, False
                        tool_details, answer_details = "", ""
                        error = (
                            exc.label
                            if isinstance(exc, APIRequestError)
                            else type(exc).__name__
                        )
                        if isinstance(exc, APIRequestError) and exc.stop_run:
                            stop_reason = exc.label
                    elapsed_ms = round((time.perf_counter() - started) * 1000)
                    values = summary[provider]
                    values["latencies"].append(elapsed_ms)
                    values["total"] += 1
                    values["tools_passed"] += int(tools_passed)
                    values["answers_passed"] += int(answer_passed)
                    cost = estimate_cost(provider, input_tokens, output_tokens)
                    writer.writerow(
                        {
                            "run_id": run_id,
                            "run_timestamp": run_at.isoformat(timespec="seconds"),
                            "provider": provider,
                            "model": model,
                            "case_id": case["id"],
                            "repetition": repetition,
                            "tool_calls_passed": tools_passed,
                            "tool_check_details": tool_details,
                            "answer_passed_auto_check": answer_passed,
                            "answer_check_details": answer_details,
                            "latency_ms": elapsed_ms,
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                            "estimated_cost_usd": cost,
                            "tool_calls": json.dumps(actual_calls, ensure_ascii=False),
                            "answer": answer.replace("\n", " ").strip(),
                            "error": error,
                        }
                    )
                    output_file.flush()
                    tool_status = "OK" if tools_passed else "REVISAR"
                    print(
                        f"{provider} | {case['id']} | {elapsed_ms} ms | "
                        f"ferramentas {tool_status}"
                    )
                    if stop_reason:
                        print(f"Parando novas chamadas: {stop_reason}")
                        break
                if stop_reason:
                    break
            if stop_reason:
                break

    print("\nResumo (checagens automaticas heuristicas; revise as respostas):")
    for provider, values in summary.items():
        total = values["total"]
        if not total:
            print(f"{provider}: nao testado")
            continue
        print(
            f"{provider}: ferramentas {100 * values['tools_passed'] / total:.1f}% | "
            f"respostas {100 * values['answers_passed'] / total:.1f}% | "
            f"mediana {statistics.median(values['latencies']):.0f} ms"
        )
    print(f"\nResultados: {output_path}")
    print("Cada caso pode exigir mais de uma requisicao HTTP por causa do ciclo de ferramentas.")
    return 1 if stop_reason else 0


if __name__ == "__main__":
    raise SystemExit(main())
