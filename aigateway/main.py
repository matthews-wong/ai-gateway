"""FastAPI wiring: the gateway's HTTP surface and its request pipeline.

Endpoints:
  * ``POST /v1/complete`` -- route -> cache -> provider (with retries) -> accounting
  * ``GET  /health``      -- liveness probe
  * ``GET  /usage``       -- token/cost accounting, per key, per model, and in total

``create_app`` is a factory so every collaborator (providers, router, cache,
accountant, retry settings, sleep) can be injected -- which is what keeps the
whole thing testable offline.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from fastapi import Depends, FastAPI, Header, HTTPException, Request

from . import accounting as accounting_mod
from . import backoff
from .accounting import UsageAccountant, cost_for
from .cache import Cache, InMemoryTTLCache, request_key
from .models import CompletionRequest, CompletionResponse, Usage, UsageReport
from .providers import (
    AnthropicProvider,
    MockProvider,
    Provider,
    ProviderError,
    ProviderResult,
)
from .router import Router, RoutingError, build_default_router

ANONYMOUS_KEY = "anonymous"


def default_providers() -> dict[str, Provider]:
    """The stock provider registry: an offline mock and the Anthropic adapter."""
    return {"mock": MockProvider(), "anthropic": AnthropicProvider()}


def create_app(
    *,
    providers: dict[str, Provider] | None = None,
    router: Router | None = None,
    cache: Cache | None = None,
    accountant: UsageAccountant | None = None,
    retries: int = 2,
    base_delay: float = 0.1,
    sleep: Callable[[float], None] = time.sleep,
    cost_table: dict[str, accounting_mod.ModelCost] | None = None,
) -> FastAPI:
    """Build a configured gateway application."""
    providers = providers if providers is not None else default_providers()
    router = router if router is not None else build_default_router(providers)
    cache = cache if cache is not None else InMemoryTTLCache()
    accountant = accountant if accountant is not None else UsageAccountant()

    app = FastAPI(
        title="ai-gateway",
        version="0.1.0",
        summary="A lightweight LLM API gateway: routing, caching, retries, accounting.",
    )
    # Expose collaborators on app.state so handlers (and tests) can reach them.
    app.state.router = router
    app.state.cache = cache
    app.state.accountant = accountant

    def get_api_key(x_api_key: str | None = Header(default=None)) -> str:
        """Resolve the caller's key from ``X-API-Key`` (accounting bucket)."""
        return x_api_key or ANONYMOUS_KEY

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/usage", response_model=UsageReport)
    def usage() -> UsageReport:
        return accountant.report()

    @app.post("/v1/complete", response_model=CompletionResponse)
    def complete(
        payload: CompletionRequest,
        request: Request,
        api_key: str = Depends(get_api_key),
    ) -> CompletionResponse:
        key = request_key(payload)

        # 1) Cache lookup -- a hit short-circuits the provider entirely.
        hit = cache.get(key)
        if hit is not None:
            return hit

        # 2) Route to a provider by model/policy.
        try:
            provider = router.select(payload.model)
        except RoutingError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        # 3) Call it through the retry/backoff wrapper (ProviderError is retryable).
        try:
            result: ProviderResult = backoff.retry_call(
                lambda: provider.complete(payload),
                retries=retries,
                base_delay=base_delay,
                sleep=sleep,
                retry_on=(ProviderError,),
            )
        except ProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        # 4) Account for tokens/cost, cache the fresh response, return it.
        cost = cost_for(
            payload.model,
            result.input_tokens,
            result.output_tokens,
            table=cost_table,
        )
        accountant.record(
            api_key,
            model=payload.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cost_usd=cost,
        )

        response = CompletionResponse(
            model=payload.model,
            provider=provider.name,
            completion=result.text,
            cached=False,
            usage=Usage(
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                total_tokens=result.input_tokens + result.output_tokens,
                cost_usd=cost,
            ),
        )
        cache.set(key, response)
        return response

    return app


# A module-level app for ``uvicorn aigateway.main:app``. Offline by default:
# unknown/non-claude models route to the deterministic MockProvider.
app = create_app()
