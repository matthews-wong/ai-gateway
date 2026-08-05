"""Token estimation, a configurable cost table, and per-key usage aggregation.

The cost table is ILLUSTRATIVE and configurable. The numbers below are rough,
publicly-informed placeholders for a portfolio demo -- they are not a billing
source of truth. Swap ``COST_TABLE`` (or pass your own to :func:`cost_for`) for
real rates.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from threading import Lock

from .models import KeyUsage, UsageReport

# A crude but deterministic heuristic: ~4 characters per token. Real providers
# return exact usage; this is only used for the offline MockProvider path.
CHARS_PER_TOKEN = 4


@dataclass(frozen=True)
class ModelCost:
    """USD price per 1,000,000 tokens, split by direction."""

    input_per_1m: float
    output_per_1m: float


# ILLUSTRATIVE / CONFIGURABLE -- not authoritative pricing. The "default" entry
# is applied to any model without an explicit row (e.g. the mock models).
COST_TABLE: dict[str, ModelCost] = {
    "claude-sonnet-5": ModelCost(input_per_1m=3.00, output_per_1m=15.00),
    "default": ModelCost(input_per_1m=0.25, output_per_1m=1.25),
}


def estimate_tokens(text: str) -> int:
    """Estimate a token count from raw text.

    Returns 0 for empty input, otherwise at least 1. Deterministic so cached
    and repeated requests report identical usage.
    """
    if not text:
        return 0
    return max(1, math.ceil(len(text) / CHARS_PER_TOKEN))


def cost_for(
    model: str,
    input_tokens: int,
    output_tokens: int,
    table: dict[str, ModelCost] | None = None,
) -> float:
    """Compute the USD cost of a request from token counts and the cost table."""
    table = table if table is not None else COST_TABLE
    rate = table.get(model) or table.get("default") or ModelCost(0.0, 0.0)
    cost = (
        input_tokens / 1_000_000 * rate.input_per_1m
        + output_tokens / 1_000_000 * rate.output_per_1m
    )
    # Round to sub-cent precision so JSON output stays readable and stable.
    return round(cost, 8)


class UsageAccountant:
    """Thread-safe aggregation of usage and cost, per API key.

    A single instance is shared across requests; the internal lock keeps
    increments consistent under FastAPI's threadpool.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._per_key: dict[str, KeyUsage] = {}

    def record(
        self,
        key: str,
        *,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
    ) -> None:
        """Add one request's usage to the running totals for ``key``."""
        with self._lock:
            acc = self._per_key.get(key) or KeyUsage()
            acc = KeyUsage(
                requests=acc.requests + 1,
                input_tokens=acc.input_tokens + input_tokens,
                output_tokens=acc.output_tokens + output_tokens,
                total_tokens=acc.total_tokens + input_tokens + output_tokens,
                cost_usd=round(acc.cost_usd + cost_usd, 8),
            )
            self._per_key[key] = acc

    def report(self) -> UsageReport:
        """Return a snapshot with per-key breakdown and a summed ``totals``."""
        with self._lock:
            per_key = {k: v.model_copy() for k, v in self._per_key.items()}

        totals = KeyUsage()
        for usage in per_key.values():
            totals = KeyUsage(
                requests=totals.requests + usage.requests,
                input_tokens=totals.input_tokens + usage.input_tokens,
                output_tokens=totals.output_tokens + usage.output_tokens,
                total_tokens=totals.total_tokens + usage.total_tokens,
                cost_usd=round(totals.cost_usd + usage.cost_usd, 8),
            )
        return UsageReport(totals=totals, per_key=per_key)
