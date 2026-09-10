import fcntl
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from sanka_bench.subscription import BASE_INSTRUCTIONS, Subscription


def test_subscription_blocks_concurrent_owner_before_launch(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    home = tmp_path / ".sanka-bench/codex"
    home.mkdir(parents=True)
    with (home / "session.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RuntimeError, match="session busy"), Subscription(time.monotonic() + 1):
            pytest.fail("must not launch")


@pytest.mark.parametrize(
    "event",
    [
        {"method": "mcpServer/startupStatus/updated", "params": {}},
        {"method": "item/commandExecution/requestApproval", "id": 1},
        {"method": "error", "params": {}},
    ],
)
def test_subscription_rejects_ambient_tools_and_errors(event):
    with pytest.raises(RuntimeError):
        Subscription.check(event)


def test_subscription_dispatches_only_to_native_runner_and_reconciles_usage():
    managed = Subscription(time.monotonic() + 1)
    starts = []

    def start(method, params):
        starts.append((method, params))
        return {"model": "test", "thread": {"id": "owned"}, "runtimeWorkspaceRoots": []}

    managed.rpc = start
    managed.total = {
        "inputTokens": 100,
        "outputTokens": 10,
        "cachedInputTokens": 20,
        "reasoningOutputTokens": 5,
    }
    events = iter(
        [
            {
                "method": "thread/settings/updated",
                "params": {"threadSettings": {"model": "test", "effort": "high"}},
            },
            {
                "method": "item/tool/call",
                "id": 9,
                "params": {
                    "threadId": "owned",
                    "callId": "call",
                    "tool": "bench_exec",
                    "arguments": {"command": "printf ok"},
                },
            },
            {
                "method": "thread/tokenUsage/updated",
                "params": {
                    "tokenUsage": {
                        "total": {
                            "inputTokens": 300,
                            "outputTokens": 30,
                            "cachedInputTokens": 50,
                            "reasoningOutputTokens": 8,
                        }
                    }
                },
            },
            {"method": "turn/completed", "params": {"turn": {"status": "completed"}}},
        ]
    )
    sent, calls = [], []
    managed.send = sent.append
    managed.next = lambda: next(events)
    runner = SimpleNamespace(
        model="test",
        effort="high",
        sanka=None,
        turns=0,
        requests=1,
        history=[{"role": "user", "content": "task"}],
        event=lambda *a, **kw: None,
        dispatch=lambda call: calls.append(call) or "ok",
    )
    result = managed(runner)
    assert starts[0][0] == "thread/start"
    assert starts[0][1]["baseInstructions"] == BASE_INSTRUCTIONS
    assert "using shell commands or Python" in starts[0][1]["baseInstructions"]
    assert calls == [{"call_id": "call", "name": "exec", "arguments": '{"command": "printf ok"}'}]
    assert sent[-1]["result"]["contentItems"] == [{"type": "inputText", "text": "ok"}]
    assert result["usage"] == {
        "input_tokens": 200,
        "output_tokens": 20,
        "input_tokens_details": {"cached_tokens": 30},
        "output_tokens_details": {"reasoning_tokens": 3},
    }
    # Unchanged thread settings are not re-emitted on a repair turn.
    followup = [
        {
            "method": "thread/tokenUsage/updated",
            "params": {
                "tokenUsage": {
                    "total": {
                        "inputTokens": 350,
                        "outputTokens": 40,
                        "cachedInputTokens": 60,
                        "reasoningOutputTokens": 10,
                    }
                }
            },
        },
        {"method": "turn/completed", "params": {"turn": {"status": "completed"}}},
    ]
    events = iter(followup)
    result = managed(runner)
    assert result["usage"]["input_tokens"] == 50
    assert result["usage"]["output_tokens"] == 10
    managed.confirmed_settings = None
    events = iter(followup)
    with pytest.raises(RuntimeError, match="omitted evidence"):
        managed(runner)
    events = iter(
        [
            {
                "method": "thread/settings/updated",
                "params": {
                    "threadSettings": {"model": "unexpected", "effort": "high"},
                },
            }
        ]
    )
    with pytest.raises(ValueError, match="changed model"):
        managed(runner)


@pytest.mark.parametrize(
    "verified,completion_thread", [(True, "owned"), (False, "owned"), (True, "other")]
)
def test_subscription_stops_only_after_accepted_verification_and_drains_usage(
    verified, completion_thread
):
    managed = Subscription(time.monotonic() + 1)
    managed.thread_id = "owned"
    managed.confirmed_settings = ("test", "high")
    events = iter(
        [
            {
                "method": "item/tool/call",
                "id": 9,
                "params": {
                    "threadId": "owned",
                    "turnId": "turn",
                    "callId": "verify",
                    "tool": "bench_verify",
                    "arguments": {"seed": None},
                },
            },
            {
                "method": "thread/tokenUsage/updated",
                "params": {
                    "tokenUsage": {
                        "total": {
                            "inputTokens": 300,
                            "cachedInputTokens": 200,
                            "outputTokens": 30,
                            "reasoningOutputTokens": 10,
                        }
                    }
                },
            },
            {
                "method": "turn/completed",
                "params": {
                    "threadId": completion_thread,
                    "turn": {"id": "turn", "status": "interrupted" if verified else "completed"},
                },
            },
        ]
    )
    sent, audit = [], []
    managed.send = sent.append
    managed.next = lambda: next(events)
    runner = SimpleNamespace(
        model="test",
        effort="high",
        sanka=Path("sanka"),
        turns=0,
        requests=1,
        history=[{"role": "user", "content": "task"}],
        verified=verified,
        usage_complete=True,
        event=lambda *a, **kw: audit.append((a, kw)),
        dispatch=lambda call: "accepted" if verified else "coverage incomplete",
    )
    if completion_thread != "owned":
        with pytest.raises(RuntimeError, match="omitted evidence"):
            managed(runner)
        return
    result = managed(runner)
    assert result["usage"]["input_tokens"] == 300
    interrupts = [event for event in sent if event.get("method") == "turn/interrupt"]
    replies = [event for event in sent if event.get("id") == 9]
    if verified:
        assert interrupts[0]["params"] == {"threadId": "owned", "turnId": "turn"}
        assert not replies  # No acknowledgement that starts another inference round.
        assert runner.usage_complete is False
        assert any(a[0] == "subscription_verified_stop" for a, kw in audit)
    else:
        assert not interrupts
        assert replies[0]["result"]["contentItems"][0]["text"] == "coverage incomplete"


def test_unrequested_subscription_interruption_is_still_a_failure():
    managed = Subscription(time.monotonic() + 1)
    managed.thread_id = "owned"
    managed.confirmed_settings = ("test", "high")
    managed.send = lambda event: None
    managed.next = lambda: {
        "method": "turn/completed",
        "params": {"threadId": "owned", "turn": {"id": "turn", "status": "interrupted"}},
    }
    runner = SimpleNamespace(
        model="test", effort="high", history=[], event=lambda *a, **kw: None, usage_complete=True
    )
    with pytest.raises(RuntimeError, match="omitted evidence"):
        managed(runner)
