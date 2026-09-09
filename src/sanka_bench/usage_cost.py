"""API-equivalent cost from saved subscription events, including interrupted turns."""

from collections.abc import Iterable, Mapping
from typing import Any

FIELDS = ("inputTokens", "cachedInputTokens", "cacheWriteInputTokens", "outputTokens")
# USD per million tokens, Standard processing. Recheck before future campaigns.
PRICE_SOURCE = "https://developers.openai.com/api/docs/pricing"
PRICE_CHECKED_AT = "2026-09-10"
OPENAI_RATES = {
    "gpt-5-6-luna": (0.2, 0.02, 0.25, 1.2),
    "gpt-5-6-terra": (2.0, 0.2, 2.5, 12.0),
    "gpt-5-6-sol": (4.0, 0.4, 5.0, 20.0),
    "gpt-6-astra": (10.0, 1.0, 12.5, 50.0),
}


def model_estimate(
    events: Iterable[Mapping[str, Any]], model: str, *, complete: bool
) -> dict[str, Any]:
    """Reporting must survive incomplete telemetry without inventing a full bill."""
    prices = OPENAI_RATES.get(model.replace(".", "-"))
    basis = {
        "pricing_source": PRICE_SOURCE,
        "pricing_checked_at": PRICE_CHECKED_AT,
        "cost_basis": "OpenAI Standard API-equivalent; not subscription charges",
    }
    if prices is None:
        return basis | {"estimated_api_cost_usd": None, "cost_status": "model-unpriced"}
    rate = dict(zip(("input", "cached_input", "cache_write", "output"), prices, strict=True))
    rate.update(long_input_multiplier=2.0, long_output_multiplier=1.5)
    try:
        return basis | subscription_estimate(events, rate, complete=complete)
    except (ValueError, KeyError, TypeError):
        return basis | {"estimated_api_cost_usd": None, "cost_status": "invalid-usage"}


def subscription_estimate(
    events: Iterable[Mapping[str, Any]],
    rate: Mapping[str, float],
    *,
    complete: bool,
    long_context_threshold: int = 272_000,
) -> dict[str, Any]:
    """Price observed responses only. Missing final usage is never extrapolated."""
    previous: dict[str, dict[str, int]] = {}
    tokens = dict.fromkeys(FIELDS, 0)
    cost = 0.0
    responses = 0
    for row in events:
        event = row.get("event", {})
        if event.get("method") != "thread/tokenUsage/updated":
            continue
        params = event["params"]
        thread = params["threadId"]
        usage = params["tokenUsage"]
        total = {k: usage["total"].get(k) for k in FIELDS}
        if any(type(v) is not int or v < 0 for v in total.values()):
            raise ValueError("missing or invalid cumulative usage")
        before = previous.get(thread, dict.fromkeys(FIELDS, 0))
        if total == before:
            continue
        delta = {k: total[k] - before[k] for k in FIELDS}
        if any(v < 0 for v in delta.values()) or any(
            delta[k] != usage["last"].get(k) for k in FIELDS
        ):
            raise ValueError("cannot establish per-response usage and context tier")
        i, c, w, o = (delta[k] for k in FIELDS)
        if c + w > i:
            raise ValueError("cache usage exceeds input")
        long = i > long_context_threshold
        cost += (
            ((i - c - w) * rate["input"] + c * rate["cached_input"] + w * rate["cache_write"])
            * (rate["long_input_multiplier"] if long else 1)
            + o * rate["output"] * (rate["long_output_multiplier"] if long else 1)
        ) / 1_000_000
        previous[thread] = total
        tokens = {k: tokens[k] + delta[k] for k in FIELDS}
        responses += 1
    return {
        "estimated_api_cost_usd": cost if responses or complete else None,
        "cost_status": "complete" if complete else "lower_bound" if responses else "unavailable",
        "observed_responses": responses,
        "observed_tokens": tokens if responses or complete else None,
    }
