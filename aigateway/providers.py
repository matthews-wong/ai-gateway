"""The ``Provider`` seam plus a bundled offline mock and a documented Anthropic backend.

Everything downstream of the router depends only on the :class:`Provider`
protocol, so new backends drop in without touching routing, caching, or
accounting. :class:`MockProvider` is deterministic and offline; the tests use it
exclusively.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from . import accounting
from .models import CompletionRequest


class ProviderError(RuntimeError):
    """Raised when a provider cannot fulfil a request.

    Treated as retryable by the gateway (see :mod:`aigateway.backoff`), so
    transient failures back off and retry while permanent ones surface after
    the retry budget is spent.
    """


@dataclass
class ProviderResult:
    """What a provider returns: the completion text and exact token counts."""

    text: str
    input_tokens: int
    output_tokens: int


@runtime_checkable
class Provider(Protocol):
    """The injectable backend contract.

    A provider has a stable ``name`` (for routing/telemetry) and a synchronous
    ``complete`` that turns a request into a :class:`ProviderResult`.
    """

    name: str

    def complete(self, request: CompletionRequest) -> ProviderResult: ...


class MockProvider:
    """A deterministic, offline provider for local dev and tests.

    The completion is a pure function of ``(model, prompt)`` so identical
    requests always yield identical output -- which is exactly what makes the
    cache and accounting behaviour testable without a network.
    """

    name = "mock"

    def complete(self, request: CompletionRequest) -> ProviderResult:
        text = self._generate(request)
        return ProviderResult(
            text=text,
            input_tokens=accounting.estimate_tokens(request.prompt),
            output_tokens=accounting.estimate_tokens(text),
        )

    @staticmethod
    def _generate(request: CompletionRequest) -> str:
        seed = f"{request.model}\x00{request.prompt}".encode()
        digest = hashlib.sha256(seed).hexdigest()[:8]
        return f"[mock:{request.model}] ({digest}) You said: {request.prompt}"


class AnthropicProvider:
    """A documented adapter for Anthropic's Messages API (model ``claude-sonnet-5``).

    Kept graceful when no key is present: construction never fails, and the
    ``anthropic`` SDK is imported lazily. The first ``complete`` call without a
    key (or without the SDK installed) raises :class:`ProviderError` with a
    clear message instead of crashing at import time. This keeps the whole
    project runnable and testable offline.

    To enable it: ``pip install ".[anthropic]"`` and set ``ANTHROPIC_API_KEY``.
    """

    name = "anthropic"

    def __init__(
        self,
        model: str = "claude-sonnet-5",
        api_key: str | None = None,
        client: Any | None = None,
        max_tokens: int = 1024,
    ) -> None:
        self._model = model
        self._api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self._client = client
        self._default_max_tokens = max_tokens

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise ProviderError(
                "AnthropicProvider needs an API key: set ANTHROPIC_API_KEY "
                "(or pass api_key=...). Running offline? Route to MockProvider."
            )
        try:
            import anthropic  # imported lazily so the package works without it
        except ImportError as exc:  # pragma: no cover - exercised only with SDK absent
            raise ProviderError(
                "The 'anthropic' package is not installed. "
                'Install it with: pip install ".[anthropic]"'
            ) from exc
        self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client

    def complete(self, request: CompletionRequest) -> ProviderResult:
        client = self._ensure_client()
        try:
            message = client.messages.create(
                model=self._model,
                max_tokens=request.max_tokens or self._default_max_tokens,
                messages=[{"role": "user", "content": request.prompt}],
            )
        except Exception as exc:  # normalise SDK/transport errors into our seam
            raise ProviderError(f"Anthropic request failed: {exc}") from exc

        text = "".join(
            block.text
            for block in message.content
            if getattr(block, "type", None) == "text"
        )
        return ProviderResult(
            text=text,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
        )
