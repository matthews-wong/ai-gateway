"""Shared test fixtures and offline helpers.

Everything here is offline: the app is built with the deterministic
MockProvider and a no-op sleep so retries never touch the wall clock.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aigateway.accounting import UsageAccountant
from aigateway.cache import InMemoryTTLCache
from aigateway.main import create_app
from aigateway.models import CompletionRequest
from aigateway.providers import MockProvider, ProviderError, ProviderResult


class FlakyProvider:
    """Fails ``fail_times`` times with ProviderError, then succeeds.

    ``calls`` records how often ``complete`` ran, so tests can assert the retry
    count precisely.
    """

    name = "flaky"

    def __init__(self, fail_times: int) -> None:
        self._fail_times = fail_times
        self.calls = 0

    def complete(self, request: CompletionRequest) -> ProviderResult:
        self.calls += 1
        if self.calls <= self._fail_times:
            raise ProviderError(f"simulated failure #{self.calls}")
        return ProviderResult(text="recovered", input_tokens=3, output_tokens=2)


@pytest.fixture
def accountant() -> UsageAccountant:
    return UsageAccountant()


@pytest.fixture
def client(accountant: UsageAccountant) -> TestClient:
    """A TestClient wired to MockProvider only, with a no-op sleep."""
    app = create_app(
        providers={"mock": MockProvider()},
        cache=InMemoryTTLCache(ttl_seconds=300.0),
        accountant=accountant,
        sleep=lambda _delay: None,
    )
    return TestClient(app)
