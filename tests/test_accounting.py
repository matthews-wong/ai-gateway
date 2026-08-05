"""Usage / cost accounting sums correctly, per key and in total."""

from __future__ import annotations

from aigateway.accounting import COST_TABLE, ModelCost, UsageAccountant, cost_for, estimate_tokens


def test_estimate_tokens_is_deterministic_and_nonzero():
    assert estimate_tokens("") == 0
    assert estimate_tokens("a") == 1
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2  # ceil(5/4)


def test_cost_for_uses_table_and_default():
    table = {
        "claude-sonnet-5": ModelCost(3.0, 15.0),
        "default": ModelCost(0.25, 1.25),
    }
    # 1,000,000 input + 1,000,000 output at the sonnet rate = 3 + 15.
    assert cost_for("claude-sonnet-5", 1_000_000, 1_000_000, table=table) == 18.0
    # Unknown model falls back to the default row.
    assert cost_for("mystery", 1_000_000, 0, table=table) == 0.25


def test_accountant_sums_per_key_and_totals():
    acc = UsageAccountant()
    acc.record("alice", input_tokens=10, output_tokens=5, cost_usd=0.01)
    acc.record("alice", input_tokens=20, output_tokens=10, cost_usd=0.02)
    acc.record("bob", input_tokens=4, output_tokens=1, cost_usd=0.005)

    report = acc.report()

    alice = report.per_key["alice"]
    assert alice.requests == 2
    assert alice.input_tokens == 30
    assert alice.output_tokens == 15
    assert alice.total_tokens == 45
    assert alice.cost_usd == 0.03

    # Totals == sum across every key.
    assert report.totals.requests == 3
    assert report.totals.input_tokens == 34
    assert report.totals.output_tokens == 16
    assert report.totals.total_tokens == 50
    assert report.totals.cost_usd == 0.035


def test_usage_endpoint_totals_match_per_key(client):
    # Three distinct (uncached) completions under two keys.
    client.post(
        "/v1/complete",
        json={"model": "mock-small", "prompt": "one"},
        headers={"X-API-Key": "key-a"},
    )
    client.post(
        "/v1/complete",
        json={"model": "mock-small", "prompt": "two"},
        headers={"X-API-Key": "key-a"},
    )
    client.post(
        "/v1/complete",
        json={"model": "mock-small", "prompt": "three"},
        headers={"X-API-Key": "key-b"},
    )

    report = client.get("/usage").json()

    assert report["per_key"]["key-a"]["requests"] == 2
    assert report["per_key"]["key-b"]["requests"] == 1
    assert report["totals"]["requests"] == 3

    summed = sum(k["cost_usd"] for k in report["per_key"].values())
    assert report["totals"]["cost_usd"] == round(summed, 8)
    assert report["totals"]["cost_usd"] > 0  # default cost table is non-zero


def test_default_cost_table_has_sonnet_and_default_rows():
    assert "claude-sonnet-5" in COST_TABLE
    assert "default" in COST_TABLE
