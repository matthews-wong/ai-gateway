"""Request/response schemas shared across the gateway.

These are the wire contracts for the HTTP API plus a couple of small value
objects used internally. Keeping them in one place makes the data flow through
route -> cache -> provider -> accounting easy to follow.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CompletionRequest(BaseModel):
    """A completion request as accepted by ``POST /v1/complete``."""

    model: str = Field(..., min_length=1, description="Logical model name used for routing.")
    prompt: str = Field(..., description="The user prompt to complete.")
    max_tokens: int = Field(default=512, ge=1, le=8192)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)


class Usage(BaseModel):
    """Per-request token counts and derived cost."""

    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float


class CompletionResponse(BaseModel):
    """The gateway's response for a single completion."""

    model: str
    provider: str
    completion: str
    cached: bool = False
    usage: Usage


class KeyUsage(BaseModel):
    """Aggregated usage for one API key (or the ``totals`` roll-up)."""

    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0


class UsageReport(BaseModel):
    """The payload returned by ``GET /usage``."""

    totals: KeyUsage
    per_key: dict[str, KeyUsage]
