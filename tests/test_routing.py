"""Routing picks the right provider by model name / policy."""

from __future__ import annotations

import pytest

from aigateway.providers import AnthropicProvider, MockProvider
from aigateway.router import Router, RoutingError, build_default_router


@pytest.fixture
def providers() -> dict:
    return {"mock": MockProvider(), "anthropic": AnthropicProvider()}


def test_claude_model_routes_to_anthropic(providers):
    router = build_default_router(providers)
    assert router.select("claude-sonnet-5").name == "anthropic"


def test_mock_prefixed_model_routes_to_mock(providers):
    router = build_default_router(providers)
    assert router.select("mock-small").name == "mock"


def test_unknown_model_falls_back_to_default(providers):
    router = build_default_router(providers)
    assert router.select("some-random-model").name == "mock"


def test_no_default_raises_routing_error(providers):
    router = Router(providers=providers, routes=[], default=None)
    with pytest.raises(RoutingError):
        router.select("anything")


def test_route_to_unknown_provider_raises(providers):
    from aigateway.router import prefix_route

    router = Router(
        providers=providers,
        routes=[prefix_route("gpt", "openai")],  # 'openai' not registered
        default=None,
    )
    with pytest.raises(RoutingError):
        router.select("gpt-4")
