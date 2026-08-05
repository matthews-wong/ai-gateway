"""Pluggable response cache with a stable request hash and an in-memory TTL default.

The cache key is a SHA-256 over the request's semantically relevant fields,
serialized deterministically (sorted keys) so identical requests always hash to
the same value. The clock is injectable so TTL expiry can be tested without real
sleeps.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from typing import Protocol

from .models import CompletionRequest, CompletionResponse


def request_key(request: CompletionRequest) -> str:
    """Return a stable cache key for ``request``.

    Only fields that change the completion participate in the hash. ``sort_keys``
    guarantees byte-identical JSON regardless of field order.
    """
    payload = {
        "model": request.model,
        "prompt": request.prompt,
        "max_tokens": request.max_tokens,
        "temperature": request.temperature,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class Cache(Protocol):
    """The cache seam: swap in Redis, memcached, etc. behind this."""

    def get(self, key: str) -> CompletionResponse | None: ...

    def set(self, key: str, value: CompletionResponse) -> None: ...


class InMemoryTTLCache:
    """A process-local cache with per-entry TTL and simple size bounding.

    ``clock`` defaults to ``time.monotonic`` but is injectable so tests can drive
    expiry deterministically. On a hit the stored value is returned with
    ``cached=True`` set on a copy, leaving the cached original untouched.
    """

    def __init__(
        self,
        ttl_seconds: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
        max_entries: int = 1024,
    ) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._max_entries = max_entries
        self._store: dict[str, tuple[float, CompletionResponse]] = {}

    def get(self, key: str) -> CompletionResponse | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if self._clock() >= expires_at:
            # Expired -- drop it and report a miss.
            self._store.pop(key, None)
            return None
        return value.model_copy(update={"cached": True})

    def set(self, key: str, value: CompletionResponse) -> None:
        if key not in self._store and len(self._store) >= self._max_entries:
            self._evict_oldest()
        expires_at = self._clock() + self._ttl
        # Store with cached=False; get() flips the flag on the returned copy.
        self._store[key] = (expires_at, value.model_copy(update={"cached": False}))

    def _evict_oldest(self) -> None:
        # Evict the entry with the nearest expiry -- cheap approximation of LRU
        # that is good enough for a bounded in-memory cache.
        oldest = min(self._store, key=lambda k: self._store[k][0])
        self._store.pop(oldest, None)
