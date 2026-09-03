#!/usr/bin/env python3
"""Create preflight evidence for one Claude Code model route.

This is an explicit, non-scored provider call. The benchmark coordinator never invokes
it automatically.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sanka_bench.environment import isolated_environment

QUALIFICATION_TEXT = "sanka-bench-claude-route-qualified\n"
QUALIFICATION_PROMPT = (
    "Create qualification.txt in the current directory with exactly this UTF-8 text, "
    "including the trailing newline: sanka-bench-claude-route-qualified. "
    "Then read the file and reply with only qualified."
)


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha256_path(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _events(stdout: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def qualify(
    *,
    claude_bin: Path,
    requested_model_id: str,
    provider: str,
    provider_variant: str,
    route_kind: str,
    billing_mode: str,
    gateway_profile: str | None,
    provider_evidence: Path,
    output: Path,
) -> dict[str, Any]:
    if route_kind == "anthropic-native":
        if billing_mode != "subscription" or gateway_profile is not None:
            raise ValueError("anthropic-native qualification requires subscription and no gateway")
    elif route_kind == "gateway":
        if billing_mode != "api_key" or not gateway_profile:
            raise ValueError("gateway qualification requires api_key and a gateway profile")
    else:
        raise ValueError("route_kind must be anthropic-native or gateway")

    evidence = _load_object(provider_evidence)
    if evidence.get("provider") != provider or evidence.get("provider_variant") != provider_variant:
        raise ValueError("provider identity does not match its evidence")
    actual_model_id = str(evidence.get("actual_model_id") or "")
    if not actual_model_id:
        raise ValueError("provider evidence must name actual_model_id")
    if evidence.get("usage_accounting") is not True:
        raise ValueError("provider evidence must confirm usage accounting")

    claude_bin = claude_bin.resolve()
    version = subprocess.run(
        [str(claude_bin), "--version"],
        capture_output=True,
        text=True,
        check=False,
        env=isolated_environment(os.environ),
    )
    if version.returncode != 0 or not version.stdout.strip():
        raise ValueError("Claude Code version probe failed")

    with tempfile.TemporaryDirectory(prefix="sanka-claude-qualification-") as temporary:
        workspace = Path(temporary)
        claude_config = workspace / "claude-config"
        claude_config.mkdir()
        route_keys = (
            {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"}
            if route_kind == "gateway"
            else set()
        )
        environment = isolated_environment(os.environ, route_keys)
        environment["CLAUDE_CONFIG_DIR"] = str(claude_config)
        outcome = subprocess.run(
            [
                str(claude_bin),
                "-p",
                QUALIFICATION_PROMPT,
                "--model",
                requested_model_id,
                "--max-turns",
                "4",
                "--output-format",
                "stream-json",
                "--verbose",
                "--dangerously-skip-permissions",
            ],
            cwd=workspace,
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        transcript = outcome.stdout
        events = _events(transcript)
        result = next((event for event in reversed(events) if event.get("type") == "result"), None)
        tool_output = workspace / "qualification.txt"
        tool_use = (
            tool_output.is_file() and tool_output.read_text(encoding="utf-8") == QUALIFICATION_TEXT
        )
        if not tool_use:
            raise ValueError("Claude Code tool-use probe did not create the expected file")
        if outcome.returncode != 0 or result is None or result.get("is_error") is True:
            raise ValueError(
                "Claude Code qualification did not produce a successful terminal event"
            )
        usage = result.get("modelUsage")
        usage_accounting = isinstance(usage, dict) and bool(usage)
        if not usage_accounting:
            raise ValueError("Claude Code qualification did not report model usage")

    output = output.resolve()
    transcript_path = output.with_suffix(".jsonl")
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.write_text(transcript, encoding="utf-8")
    record: dict[str, Any] = {
        "schema": "sanka-bench/claude-route-qualification/v1",
        "status": "qualified",
        "qualified_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "requested_model_id": requested_model_id,
        "actual_model_id": actual_model_id,
        "provider": provider,
        "provider_variant": provider_variant,
        "route_kind": route_kind,
        "billing_mode": billing_mode,
        "gateway_profile": gateway_profile,
        "claude": {
            "version": version.stdout.strip(),
            "sha256": sha256_path(claude_bin),
        },
        "checks": {
            "tool_use": tool_use,
            "streaming": len(events) > 1,
            "terminal_event": True,
            "usage_accounting": usage_accounting,
        },
        "evidence": {
            "prompt_sha256": sha256_bytes(QUALIFICATION_PROMPT.encode()),
            "provider_sha256": sha256_path(provider_evidence),
            "transcript_sha256": sha256_path(transcript_path),
        },
    }
    _atomic_json(output, record)
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--claude-bin", type=Path, required=True)
    parser.add_argument("--requested-model-id", required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--provider-variant", required=True)
    parser.add_argument("--route-kind", choices=("anthropic-native", "gateway"), required=True)
    parser.add_argument("--billing-mode", choices=("subscription", "api_key"), required=True)
    parser.add_argument("--gateway-profile")
    parser.add_argument("--provider-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        record = qualify(
            claude_bin=args.claude_bin,
            requested_model_id=args.requested_model_id,
            provider=args.provider,
            provider_variant=args.provider_variant,
            route_kind=args.route_kind,
            billing_mode=args.billing_mode,
            gateway_profile=args.gateway_profile,
            provider_evidence=args.provider_evidence,
            output=args.output,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        print(f"qualification failed: {exc}")
        return 2
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
