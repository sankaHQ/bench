import io
import json
import time
from types import SimpleNamespace

import pytest

from sanka_bench.fireworks_stream import read_stream


def stream(*, done=True, usage=True):
    chunks = [
        {
            "model": "test",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "reasoning_content": "thinking",
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call1",
                                "function": {"name": "exec", "arguments": '{"command":'},
                            }
                        ],
                    },
                }
            ],
        },
        {
            "model": "test",
            "choices": [
                {
                    "index": 0,
                    "delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"true"}'}}]},
                    "finish_reason": "tool_calls",
                }
            ],
        },
    ]
    if usage:
        chunks.append({"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
    return io.BytesIO(
        (
            "".join("data: " + json.dumps(x) + "\n\n" for x in chunks)
            + ("data: [DONE]\n\n" if done else "")
        ).encode()
    )


def test_stream_assembles_complete_tools_and_usage_with_safe_progress():
    events = []
    timeouts = []
    conn = SimpleNamespace(settimeout=timeouts.append)
    result = read_stream(
        stream(),
        conn,
        time.monotonic() + 30,
        time.monotonic(),
        lambda kind, **data: events.append((kind, data)),
    )
    message = result["choices"][0]["message"]
    assert message["tool_calls"][0]["function"] == {
        "name": "exec",
        "arguments": '{"command":"true"}',
    }
    assert message["reasoning_content"] == "thinking"
    assert result["usage"]["completion_tokens"] == 5
    assert events and "thinking" not in str(events) and "command" not in str(events)
    assert all(0 < timeout <= 30 for timeout in timeouts)


@pytest.mark.parametrize("done,usage", [(False, True), (True, False)])
def test_incomplete_stream_never_returns_partial_tools(done, usage):
    with pytest.raises(ValueError):
        read_stream(
            stream(done=done, usage=usage),
            None,
            time.monotonic() + 30,
            time.monotonic(),
            lambda *args, **kw: None,
        )


def test_stream_respects_absolute_deadline():
    with pytest.raises(TimeoutError):
        read_stream(
            stream(), None, time.monotonic() - 1, time.monotonic(), lambda *args, **kw: None
        )


def test_transport_cancels_trickling_response(monkeypatch):
    import http.client
    import socket
    import threading

    from sanka_bench import fireworks_stream

    client, server = socket.socketpair()

    class Connection:
        sock = client

        def __init__(self, *args, **kwargs):
            pass

        def connect(self):
            pass

        def request(self, *args):
            pass

        def getresponse(self):
            response = http.client.HTTPResponse(client)
            response.begin()
            return response

        def close(self):
            client.close()

    def send():
        try:
            server.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n\r\n")
            for _ in range(100):
                server.sendall(b"x")
                time.sleep(0.01)
        except OSError:
            pass
        finally:
            server.close()

    monkeypatch.setattr(fireworks_stream.http.client, "HTTPSConnection", Connection)
    worker = threading.Thread(target=send)
    worker.start()
    started = time.monotonic()
    try:
        with pytest.raises((ValueError, OSError)):
            fireworks_stream.complete({}, "fake", 0.1, lambda *args, **kw: None)
        assert time.monotonic() - started < 0.8
    finally:
        client.close()
        worker.join(timeout=2)
    assert not worker.is_alive()


@pytest.mark.parametrize("error", [KeyError, TypeError, AttributeError])
def test_malformed_transport_keeps_usage_unknown(tmp_path, monkeypatch, error):
    from sanka_bench import fireworks_stream, native_agent

    class Response(io.BytesIO):
        status = 200

        def getheader(self, *args):
            return "text/event-stream"

    class Connection:
        sock = SimpleNamespace(settimeout=lambda value: None)

        def __init__(self, *args, **kwargs):
            pass

        def connect(self):
            pass

        def request(self, *args):
            pass

        def getresponse(self):
            return Response()

        def close(self):
            pass

    def malformed(*args):
        raise error("malformed")

    monkeypatch.setattr(fireworks_stream.http.client, "HTTPSConnection", Connection)
    monkeypatch.setattr(fireworks_stream, "read_stream", malformed)
    run = native_agent.Runner(
        provider="fireworks",
        model="test",
        effort="high",
        key="fake",
        prompt="test",
        workspace=tmp_path,
        artifacts=tmp_path / "artifacts",
        execute=lambda *a, **k: pytest.fail("partial tool must not execute"),
        promote=lambda: {},
        sanka=None,
        target="fiber",
        max_turns=5,
        wall_seconds=5,
        price_in=1,
        price_out=1,
    )
    outcome, stats = run.run()
    assert outcome.returncode == 1
    assert stats["usage_complete"] is False and stats["cost_usd"] is None
    assert stats["work"]["provider_api_requests"] == 1
    assert stats["work"]["provider_retries"] == 0


def test_late_connection_never_sends_request(monkeypatch):
    from sanka_bench import fireworks_stream

    class Connection:
        sock = None

        def __init__(self, *args, **kwargs):
            pass

        def connect(self):
            time.sleep(0.03)

        def request(self, *args):
            pytest.fail("must not send after wall deadline")

        def close(self):
            pass

    monkeypatch.setattr(fireworks_stream.http.client, "HTTPSConnection", Connection)
    with pytest.raises(TimeoutError, match="connection exceeded"):
        fireworks_stream.complete({}, "fake", 0.01, lambda *a, **k: None)
