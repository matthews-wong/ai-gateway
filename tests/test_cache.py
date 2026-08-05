"""An identical request is served from cache on the second call."""

from __future__ import annotations

from aigateway.cache import InMemoryTTLCache, request_key
from aigateway.models import CompletionRequest, CompletionResponse, Usage


def _response(text: str = "hi") -> CompletionResponse:
    return CompletionResponse(
        model="mock-small",
        provider="mock",
        completion=text,
        cached=False,
        usage=Usage(input_tokens=1, output_tokens=1, total_tokens=2, cost_usd=0.0),
    )


def test_second_identical_request_is_cached(client):
    body = {"model": "mock-small", "prompt": "hello world"}

    first = client.post("/v1/complete", json=body)
    assert first.status_code == 200
    assert first.json()["cached"] is False

    second = client.post("/v1/complete", json=body)
    assert second.status_code == 200
    assert second.json()["cached"] is True

    # Same completion text served both times (deterministic provider).
    assert first.json()["completion"] == second.json()["completion"]


def test_different_prompt_is_not_cached(client):
    a = client.post("/v1/complete", json={"model": "mock-small", "prompt": "a"})
    b = client.post("/v1/complete", json={"model": "mock-small", "prompt": "b"})
    assert a.json()["cached"] is False
    assert b.json()["cached"] is False


def test_request_key_is_stable_and_field_sensitive():
    r1 = CompletionRequest(model="m", prompt="p", max_tokens=10, temperature=0.5)
    r2 = CompletionRequest(model="m", prompt="p", max_tokens=10, temperature=0.5)
    r3 = CompletionRequest(model="m", prompt="p", max_tokens=11, temperature=0.5)
    assert request_key(r1) == request_key(r2)
    assert request_key(r1) != request_key(r3)


def test_ttl_expiry_uses_injected_clock():
    now = {"t": 0.0}
    cache = InMemoryTTLCache(ttl_seconds=10.0, clock=lambda: now["t"])
    cache.set("k", _response())

    assert cache.get("k") is not None  # within TTL

    now["t"] = 10.0  # at/after expiry
    assert cache.get("k") is None


def test_cache_hit_sets_cached_flag_without_mutating_stored_value():
    cache = InMemoryTTLCache(ttl_seconds=10.0, clock=lambda: 0.0)
    cache.set("k", _response())
    got = cache.get("k")
    assert got is not None and got.cached is True
    # Fetching again still reports a hit (stored copy untouched).
    again = cache.get("k")
    assert again is not None and again.cached is True
