"""Messages wire translation; execution stays in the existing native Runner."""

from __future__ import annotations

import json
from typing import Any


def payload(
    history: list[dict[str, Any]],
    specs: list[dict[str, Any]],
    *,
    model: str,
    effort: str,
    max_tokens: int,
) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    for item in history:
        role = item["role"]
        if role == "tool":
            role = "user"
            content = [
                {
                    "type": "tool_result",
                    "tool_use_id": item["tool_call_id"],
                    "content": item["content"],
                }
            ]
        elif role == "assistant":
            content = item["anthropic_content"]
        else:
            content = [{"type": "text", "text": item["content"]}]
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"].extend(content)
        else:
            messages.append({"role": role, "content": list(content)})
    # Copy before marking: thinking signatures and stored history remain unchanged.
    messages[-1]["content"][-1] = {
        **messages[-1]["content"][-1],
        "cache_control": {"type": "ephemeral", "ttl": "5m"},
    }
    return {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": effort},
        "tools": [
            {"name": s["name"], "description": s["description"], "input_schema": s["parameters"]}
            for s in specs
        ],
        "tool_choice": {"type": "auto", "disable_parallel_tool_use": True},
    }


def response(data: dict[str, Any]) -> dict[str, Any]:
    usage, content = data["usage"], data["content"]
    counts = [
        usage.get(k)
        for k in (
            "input_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
            "output_tokens",
        )
    ]
    if any(type(v) is not int or v < 0 for v in counts):
        raise ValueError("Anthropic omitted valid cache-aware usage")
    if not isinstance(content, list) or not all(isinstance(b, dict) for b in content):
        raise ValueError("invalid Anthropic content")
    calls = []
    for block in content:
        if block.get("type") == "tool_use":
            if not isinstance(block.get("input"), dict):
                raise ValueError("invalid Anthropic tool input")
            calls.append(
                {
                    "id": block["id"],
                    "type": "function",
                    "function": {"name": block["name"], "arguments": json.dumps(block["input"])},
                }
            )
    reason = {"tool_use": "tool_calls", "end_turn": "stop"}.get(
        str(data.get("stop_reason")), "length"
    )
    return {
        "model": data["model"],
        "usage": {
            "prompt_tokens": sum(counts[:3]),
            "completion_tokens": counts[3],
            "prompt_tokens_details": {"cached_tokens": counts[1]},
            "cache_creation_input_tokens": counts[2],
            "completion_tokens_details": {
                "reasoning_tokens": usage.get("output_tokens_details", {}).get("thinking_tokens")
            },
        },
        "choices": [
            {
                "finish_reason": reason,
                "message": {
                    "role": "assistant",
                    "content": "",
                    "anthropic_content": content,
                    "tool_calls": calls,
                },
            }
        ],
    }
