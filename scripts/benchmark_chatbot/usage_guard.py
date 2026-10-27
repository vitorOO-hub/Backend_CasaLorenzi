from __future__ import annotations

import os


class RequestLimitExceeded(RuntimeError):
    pass


class RequestBudget:
    """Caps outbound provider requests for one benchmark process."""

    def __init__(self, max_requests: int) -> None:
        if max_requests < 1:
            raise ValueError("max_requests precisa ser pelo menos 1")
        self.max_requests = max_requests
        self.used = 0

    def before_request(self, _request: object) -> None:
        if self.used >= self.max_requests:
            raise RequestLimitExceeded(
                f"Limite local de {self.max_requests} chamadas atingido; "
                "nenhuma nova requisicao foi enviada."
            )
        self.used += 1


def resolve_max_requests(cli_value: int | None) -> int:
    raw_value = str(cli_value) if cli_value is not None else os.getenv(
        "BENCH_MAX_API_REQUESTS", "20"
    )
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError("BENCH_MAX_API_REQUESTS precisa ser um inteiro") from exc
    if value < 1:
        raise ValueError("o limite de chamadas precisa ser pelo menos 1")
    return value
