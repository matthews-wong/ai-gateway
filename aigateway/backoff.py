"""Retry with exponential backoff and an injectable sleep.

The ``sleep`` callable is a parameter so retry timing can be tested without
wall-clock delays -- pass a fake that records durations instead of sleeping.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def compute_delay(
    attempt: int,
    base_delay: float,
    factor: float,
    max_delay: float,
) -> float:
    """Delay before retry ``attempt`` (1-based), capped at ``max_delay``."""
    return min(base_delay * (factor ** (attempt - 1)), max_delay)


def retry_call(
    func: Callable[[], T],
    *,
    retries: int = 2,
    base_delay: float = 0.1,
    factor: float = 2.0,
    max_delay: float = 10.0,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    sleep: Callable[[float], None] = None,  # type: ignore[assignment]
    jitter: Callable[[float], float] | None = None,
) -> T:
    """Call ``func`` and retry on failure with exponential backoff.

    ``retries`` is the number of *additional* attempts after the first, so the
    total attempt count is ``retries + 1``. Exceptions not listed in
    ``retry_on`` propagate immediately; the last exception is re-raised once the
    budget is exhausted.
    """
    if sleep is None:  # avoid importing time at module scope for pure-logic tests
        import time

        sleep = time.sleep

    attempt = 0
    while True:
        try:
            return func()
        except retry_on:
            attempt += 1
            if attempt > retries:
                raise
            delay = compute_delay(attempt, base_delay, factor, max_delay)
            if jitter is not None:
                delay = jitter(delay)
            sleep(delay)
