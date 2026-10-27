import httpx
import pytest

from scripts.benchmark_chatbot.usage_guard import (
    RequestBudget,
    RequestLimitExceeded,
    resolve_max_requests,
)


def test_request_budget_blocks_before_sending_over_limit() -> None:
    sent = []
    budget = RequestBudget(2)

    def respond(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200)

    with httpx.Client(
        transport=httpx.MockTransport(respond),
        event_hooks={"request": [budget.before_request]},
    ) as client:
        client.get("https://example.test/one")
        client.get("https://example.test/two")
        with pytest.raises(RequestLimitExceeded):
            client.get("https://example.test/three")

    assert len(sent) == 2
    assert budget.used == 2


def test_resolve_max_requests_uses_conservative_default(monkeypatch) -> None:
    monkeypatch.delenv("BENCH_MAX_API_REQUESTS", raising=False)
    assert resolve_max_requests(None) == 20


def test_resolve_max_requests_reads_env_and_cli_override(monkeypatch) -> None:
    monkeypatch.setenv("BENCH_MAX_API_REQUESTS", "35")
    assert resolve_max_requests(None) == 35
    assert resolve_max_requests(12) == 12


@pytest.mark.parametrize("value", [0, -1])
def test_resolve_max_requests_rejects_nonpositive_values(value: int) -> None:
    with pytest.raises(ValueError):
        resolve_max_requests(value)
