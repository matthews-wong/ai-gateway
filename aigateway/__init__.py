"""ai-gateway: a lightweight LLM API gateway.

Sits in front of multiple LLM providers and adds routing, response caching,
retries with backoff, and token/cost accounting. Offline-first: the bundled
``MockProvider`` is fully deterministic and needs no network or API key.
"""

from __future__ import annotations

__version__ = "0.1.0"

from .main import create_app

__all__ = ["create_app", "__version__"]
