"""Retries then succeed on a flaky provider -- with no real sleeps."""

from __future__ import annotations

import pytest

from aigateway import backoff
from aigateway.models import CompletionRequest
from aigateway.providers import ProviderError

from .conftest import FlakyProvider


def _request() -> CompletionRequest:
    return CompletionRequest(model="mock-small", prompt="retry me")


def test_flaky_provider_succeeds_after_retries():
    provider = FlakyProvider(fail_times=2)
    slept: list[float] = []

    result = backoff.retry_call(
        lambda: provider.complete(_request()),
        retries=3,
        base_delay=0.1,
        sleep=slept.append,
        retry_on=(ProviderError,),
    )

    assert result.text == "recovered"
    assert provider.calls == 3  # 2 failures + 1 success
    assert len(slept) == 2  # one backoff sleep per failure


def test_exponential_backoff_delays():
    provider = FlakyProvider(fail_times=2)
    slept: list[float] = []

    backoff.retry_call(
        lambda: provider.complete(_request()),
        retries=3,
        base_delay=0.1,
        factor=2.0,
        sleep=slept.append,
        retry_on=(ProviderError,),
    )

    assert slept == [0.1, 0.2]  # base, base*factor


def test_retries_exhausted_reraises_last_error():
    provider = FlakyProvider(fail_times=5)
    slept: list[float] = []

    with pytest.raises(ProviderError):
        backoff.retry_call(
            lambda: provider.complete(_request()),
            retries=2,
            sleep=slept.append,
            retry_on=(ProviderError,),
        )

    assert provider.calls == 3  # initial + 2 retries
    assert len(slept) == 2


def test_non_retryable_exception_propagates_immediately():
    def boom():
        raise ValueError("not retryable")

    slept: list[float] = []
    with pytest.raises(ValueError):
        backoff.retry_call(
            boom,
            retries=3,
            sleep=slept.append,
            retry_on=(ProviderError,),
        )
    assert slept == []  # never retried
