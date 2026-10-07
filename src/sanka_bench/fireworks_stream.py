"""Bounded Fireworks SSE transport; never dispatch partial tool arguments."""

from __future__ import annotations

import http.client
import json
import socket
import ssl
import threading
import time
import urllib.error
from collections.abc import Callable
from contextlib import suppress
from typing import Any


def complete(
    payload: dict[str, Any], key: str, timeout: float, event: Callable[..., None]
) -> dict[str, Any]:
    started = time.monotonic()
    deadline = started + timeout
    # No environment proxies or redirect following; credentials stay on this host.
    connection = http.client.HTTPSConnection("api.fireworks.ai", timeout=min(timeout, 120))
    transport_socket = None
    phase = "connect"
    phase_started = started
    phase_seconds: dict[str, float] = {}
    body = json.dumps({**payload, "stream": True, "stream_options": {"include_usage": True}})
    event(
        "provider_request_start",
        started_at_unix=time.time(),
        request_bytes=len(body.encode("utf-8")),
        idle_timeout_seconds=120,
    )

    def cancel() -> None:
        active = transport_socket or connection.sock
        if active is not None:
            with suppress(OSError):
                active.shutdown(socket.SHUT_RDWR)
                active.close()

    # A socket idle timeout alone cannot bound a peer trickling an unfinished line.
    timer = threading.Timer(timeout, cancel)
    timer.daemon = True
    timer.start()
    try:
        # DNS resolution follows the host resolver timeout. Never send a paid
        # request if connection establishment consumed the wall budget.
        for attempt in range(2):
            try:
                connection.connect()
                break
            except (ssl.SSLEOFError, ConnectionResetError, TimeoutError) as exc:
                # No HTTP bytes were sent: one reconnect cannot duplicate inference.
                if attempt or time.monotonic() >= deadline:
                    raise
                connection.close()
                event("provider_connection_retry", category=type(exc).__name__)
                connection = http.client.HTTPSConnection(
                    "api.fireworks.ai", timeout=min(deadline - time.monotonic(), 120)
                )
        if time.monotonic() >= deadline:
            raise TimeoutError("connection exceeded wall deadline")
        connection.sock.settimeout(min(deadline - time.monotonic(), 120))
        now = time.monotonic()
        phase_seconds[phase] = now - phase_started
        phase, phase_started = "send", now
        connection.request(
            "POST",
            "/inference/v1/chat/completions",
            body,
            {"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        )
        transport_socket = connection.sock
        now = time.monotonic()
        phase_seconds[phase] = now - phase_started
        phase, phase_started = "headers", now
        response = connection.getresponse()
        if response.status != 200:
            raise urllib.error.HTTPError(
                "https://api.fireworks.ai/inference/v1/chat/completions",
                response.status,
                "provider rejected request",
                response.headers,
                None,
            )
        if "text/event-stream" not in response.getheader("Content-Type", ""):
            raise ValueError("provider did not return an event stream")
        now = time.monotonic()
        phase_seconds[phase] = now - phase_started
        event(
            "provider_response_headers",
            status=response.status,
            phase_seconds=dict(phase_seconds),
            request_elapsed_seconds=now - started,
        )
        phase, phase_started = "stream", now
        with response:
            return read_stream(response, transport_socket, deadline, started, event)
    except (
        OSError,
        ValueError,
        http.client.HTTPException,
        KeyError,
        TypeError,
        AttributeError,
    ) as exc:
        now = time.monotonic()
        event(
            "provider_transport_error",
            phase=phase,
            category=type(exc).__name__,
            request_may_have_been_sent=phase != "connect",
            request_elapsed_seconds=now - started,
            phase_seconds={**phase_seconds, phase: now - phase_started},
        )
        if isinstance(exc, (http.client.HTTPException, KeyError, TypeError, AttributeError)):
            raise ValueError("provider HTTP stream interrupted or malformed") from None
        raise
    finally:
        timer.cancel()
        timer.join()
        connection.close()


def read_stream(
    response: Any,
    transport_socket: Any,
    deadline: float,
    started: float,
    event: Callable[..., None],
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": "", "reasoning_content": ""}
    calls: dict[int, dict[str, Any]] = {}
    metadata: dict[str, Any] = {}
    model = None
    usage = None
    finish = None
    data: list[str] = []
    received = chunks = 0
    last_progress = started - 10
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("provider stream exceeded wall deadline")
        # Bound both idle reads and the overall deadline, including a slow stream.
        if transport_socket is not None:
            transport_socket.settimeout(min(remaining, 120))
        line = response.readline(1024 * 1024 + 1)
        if not line:
            raise ValueError("provider stream ended before DONE")
        received += len(line)
        if len(line) > 1024 * 1024 or received > 32 * 1024 * 1024:
            raise ValueError("provider stream exceeded size limit")
        text = line.decode("utf-8").rstrip("\r\n")
        if text.startswith("data:"):
            data.append(text[5:].lstrip(" "))
        if text or not data:
            continue
        record = "\n".join(data)
        data.clear()
        if record == "[DONE]":
            if not model or finish is None or not isinstance(usage, dict):
                raise ValueError("provider stream omitted completion or usage")
            if calls:
                message["tool_calls"] = [calls[index] for index in sorted(calls)]
            return {
                **metadata,
                "model": model,
                "choices": [{"finish_reason": finish, "message": message}],
                "usage": usage,
            }
        chunk = json.loads(record)
        if not isinstance(chunk, dict) or "error" in chunk:
            raise ValueError("invalid provider stream chunk")
        # Preserve correlation evidence even when a later read fails before DONE.
        new_metadata: dict[str, Any] = {}
        identifier = chunk.get("id")
        if "id" not in metadata and isinstance(identifier, str) and 0 < len(identifier) <= 256:
            new_metadata["id"] = identifier
        created = chunk.get("created")
        if "created" not in metadata and type(created) is int and created >= 0:
            new_metadata["created"] = created
        if new_metadata:
            metadata.update(new_metadata)
            event("provider_response_metadata", **metadata)
        if chunk.get("model"):
            if model is not None and model != chunk["model"]:
                raise ValueError("provider model changed within stream")
            model = chunk["model"]
        if chunk.get("usage") is not None:
            usage = chunk["usage"]
        choices = chunk.get("choices", [])
        if not isinstance(choices, list) or len(choices) > 1:
            raise ValueError("invalid provider stream choices")
        for choice in choices:
            if not isinstance(choice, dict):
                raise ValueError("invalid provider stream choice")
            if choice.get("index") != 0:
                raise ValueError("unexpected provider choice index")
            if choice.get("finish_reason") is not None:
                finish = choice["finish_reason"]
            delta = choice.get("delta", {})
            if not isinstance(delta, dict):
                raise ValueError("invalid provider stream delta")
            for name in ("content", "reasoning_content"):
                if delta.get(name) is not None:
                    message[name] += delta[name]
            for fragment in delta.get("tool_calls") or []:
                if not isinstance(fragment, dict):
                    raise ValueError("invalid tool stream fragment")
                index = fragment["index"]
                if type(index) is not int or not 0 <= index < 64:
                    raise ValueError("invalid tool stream index")
                call = calls.setdefault(
                    index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                )
                call["id"] += fragment.get("id") or ""
                for name in ("name", "arguments"):
                    call["function"][name] += (fragment.get("function") or {}).get(name) or ""
        chunks += 1
        now = time.monotonic()
        if now - last_progress >= 5:
            event(
                "provider_stream_progress",
                chunks=chunks,
                bytes=received,
                request_elapsed_seconds=now - started,
            )
            last_progress = now
