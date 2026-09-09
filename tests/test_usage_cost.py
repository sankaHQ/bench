import pytest

from sanka_bench.usage_cost import subscription_estimate


def test_interrupted_cost_preserves_cache_and_deduplicates():
    rate = {
        "input": 2,
        "cached_input": 0.2,
        "cache_write": 2.5,
        "output": 12,
        "long_input_multiplier": 2,
        "long_output_multiplier": 1.5,
    }
    usage = {
        "inputTokens": 300000,
        "cachedInputTokens": 100000,
        "cacheWriteInputTokens": 10000,
        "outputTokens": 1000,
    }
    event = {
        "event": {
            "method": "thread/tokenUsage/updated",
            "params": {"threadId": "a", "tokenUsage": {"total": usage, "last": usage}},
        }
    }
    result = subscription_estimate([event, event], rate, complete=False)
    assert result["estimated_api_cost_usd"] == pytest.approx(0.868)
    assert result["observed_responses"] == 1
    assert result["cost_status"] == "lower_bound"
    assert subscription_estimate([], rate, complete=False)["estimated_api_cost_usd"] is None
    event["event"]["params"]["tokenUsage"]["last"] = usage | {"inputTokens": 1}
    with pytest.raises(ValueError, match="per-response"):
        subscription_estimate([event], rate, complete=True)
