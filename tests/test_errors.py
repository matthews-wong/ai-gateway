"""Error propagation across the HTTP boundary and the offline provider path.

These lock down the failure modes the happy-path tests don't exercise: an
upstream provider fault surfaces as 502 (not a 500 crash), a routing miss is a
client error (400), and the Anthropic adapter degrades gracefully with a clear
message instead of touching the network when no key is configured.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aigateway.main import create_app
from aigateway.models import CompletionRequest
from aigateway.providers import AnthropicProvider, ProviderError, ProviderResult
from aigateway.router import Router


class _AlwaysFail:
    """A provider that always raises the retryable ProviderError."""

    name = "boom"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, request: CompletionRequest) -> ProviderResult:
        self.calls += 1
        raise ProviderError("upstream unavailable")


def test_provider_failure_after_retries_returns_502():
    provider = _AlwaysFail()
    app = create_app(
        providers={"mock": provider},
        retries=2,
        sleep=lambda _delay: None,  # no real sleeps
    )
    client = TestClient(app)

    resp = client.post("/v1/complete", json={"model": "mock-x", "prompt": "hi"})

    assert resp.status_code == 502
    assert "upstream unavailable" in resp.json()["detail"]
    assert provider.calls == 3  # initial + 2 retries, then propagate


def test_unroutable_model_returns_400():
    # A router with no routes and no default cannot place the request.
    app = create_app(
        providers={"mock": _AlwaysFail()},
        router=Router(providers={}, routes=[], default=None),
        sleep=lambda _delay: None,
    )
    client = TestClient(app)

    resp = client.post("/v1/complete", json={"model": "anything", "prompt": "hi"})

    assert resp.status_code == 400


def test_anthropic_provider_without_key_raises_clear_error():
    # No key and no injected client: must fail loudly with guidance, never crash
    # at import/construction and never reach the network.
    provider = AnthropicProvider(api_key=None)
    with pytest.raises(ProviderError) as exc:
        provider.complete(CompletionRequest(model="claude-sonnet-5", prompt="hi"))
    assert "API key" in str(exc.value)
