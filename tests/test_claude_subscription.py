import fcntl
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from sanka_bench.claude_subscription import ClaudeSubscription
from sanka_bench.usage_cost import model_estimate


def test_claude_account_lock_blocks_second_owner(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    home = tmp_path / ".sanka-bench/claude"
    home.mkdir(parents=True)
    with (home / "session.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError), ClaudeSubscription(time.monotonic() + 1):
            pytest.fail("must not acquire another account lease")


def test_claude_tool_boundary_and_verified_stop():
    transport = ClaudeSubscription(time.monotonic() + 1)
    calls = []
    runner = SimpleNamespace(
        sanka=None,
        verified=False,
        dispatch=lambda c: calls.append(c) or "ok",
        event=lambda *a, **kw: None,
    )
    request = {
        "subtype": "mcp_message",
        "server_name": "bench",
        "message": {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "exec", "arguments": {"command": "echo ok"}},
        },
    }
    assert transport.mcp(runner, request)["mcp_response"]["result"]["content"][0]["text"] == "ok"
    assert len(calls) == 1
    runner.verified = True
    with pytest.raises(ValueError, match="after verified"):
        transport.mcp(runner, request)
    request["server_name"] = "ambient"
    with pytest.raises(ValueError, match="isolation"):
        transport.mcp(runner, request)
    assert len(calls) == 1


def test_claude_cost_uses_cache_ttl_and_latest_usage_without_double_counting():
    usage = {
        "input_tokens": 100,
        "output_tokens": 50,
        "cache_read_input_tokens": 1000,
        "cache_creation_input_tokens": 300,
        "cache_creation": {"ephemeral_5m_input_tokens": 100, "ephemeral_1h_input_tokens": 200},
    }
    row = {"type": "claude_usage", "message_id": "one", "model": "claude-sonnet-5", "usage": usage}
    result = model_estimate([row, row], "claude-sonnet-5", complete=False)
    assert result["estimated_api_cost_usd"] == pytest.approx(0.00195)
    assert result["observed_responses"] == 1
    assert result["observed_tokens"]["inputTokens"] == 1400
    assert result["cost_status"] == "lower_bound"
    usage["cache_creation"]["ephemeral_1h_input_tokens"] = 0
    assert model_estimate([row], "claude-sonnet-5", complete=True)["cost_status"] == "invalid-usage"


def test_claude_verified_stop_never_acknowledges_or_runs_queued_tool():
    transport = ClaudeSubscription(time.monotonic() + 1)
    transport.started = True
    transport.thread_id = "initialized"
    sent, stopped = [], []
    transport.send = sent.append
    transport._stop = lambda: stopped.append(True)
    usage = {
        "input_tokens": 2,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "output_tokens": 10,
    }
    events = iter(
        [
            {
                "type": "assistant",
                "message": {"id": "one", "model": "claude-sonnet-5", "usage": usage},
            },
            {
                "type": "control_request",
                "request_id": "verify",
                "request": {
                    "subtype": "mcp_message",
                    "server_name": "bench",
                    "message": {
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": "verify", "arguments": {"seed": None}},
                    },
                },
            },
            {"type": "unexpected_queued_call"},
        ]
    )
    transport.next = lambda: next(events)
    runner = SimpleNamespace(
        model="claude-sonnet-5",
        sanka="sanka",
        verified=False,
        usage_complete=True,
        history=[{"role": "user", "content": "task"}],
        turns=0,
        requests=1,
        max_turns=60,
        event=lambda *a, **kw: None,
    )

    def dispatch(call):
        assert call["name"] == "verify"
        runner.verified = True
        return "passed"

    runner.dispatch = dispatch
    result = transport(runner)
    assert result["usage"]["completion_tokens"] == 10
    assert stopped == [True] and not runner.usage_complete
    assert len(sent) == 1 and sent[0]["type"] == "user"
    assert next(events)["type"] == "unexpected_queued_call"
