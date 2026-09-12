"""Explicit paid, tiny tool round-trip before admitting a native route to a matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
from pathlib import Path

from sanka_bench import agent_isolation, native_agent
from sanka_bench.environment import isolated_environment


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True, choices=native_agent.ROUTES)
    parser.add_argument("--model", required=True)
    parser.add_argument("--subscription-bin", type=Path)
    parser.add_argument("--billing-mode", choices=("api_key", "subscription"), default="api_key")
    parser.add_argument("--actual-model-id")
    parser.add_argument("--provider-variant", default="standard")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-output-tokens", type=int, default=native_agent.MAX_OUTPUT_TOKENS)
    parser.add_argument("--max-context-bytes", type=int, default=native_agent.MAX_CONTEXT_BYTES)
    args = parser.parse_args()
    if args.max_output_tokens <= 0:
        parser.error("--max-output-tokens must be positive")
    if args.max_context_bytes <= 0:
        parser.error("--max-context-bytes must be positive")
    key = os.environ.get(native_agent.ROUTES[args.provider][1])
    managed = args.billing_mode == "subscription"
    if managed and args.provider not in {"openai", "anthropic"}:
        parser.error("subscription qualification requires OpenAI")
    if not managed and (not key or args.provider == "anthropic"):
        parser.error("selected provider API key is missing")
    if managed:
        key = ""
    root = args.out.resolve().parent / (args.out.stem + "-probe")
    if args.out.exists() or args.out.with_suffix(".jsonl").exists() or root.exists():
        parser.error("qualification already exists; preserve its evidence")
    root.mkdir(parents=True)
    workspace, artifacts, home = root / "workspace", root / "artifacts", root / "home"
    for folder in (workspace, home, artifacts / "tools"):
        folder.mkdir(parents=True)
    nonce = secrets.token_hex(8)
    prompt = f"Use exec to write exactly {nonce} into probe.txt. After the tool result, reply done."
    env = isolated_environment(os.environ)
    env.update(HOME=str(home), TMPDIR=str(home))

    def execute(argv: list[str], *, timeout: float):
        return agent_isolation.run(
            argv,
            workspace=workspace,
            readable=[Path(sys.prefix), Path(sys.base_prefix)],
            writable=[workspace, home],
            env=env,
            timeout=timeout,
        )

    runner = native_agent.Runner(
        provider=args.provider,
        model=args.model,
        expected_model=args.actual_model_id or args.model,
        effort="high",
        key=key,
        prompt=prompt,
        workspace=workspace,
        artifacts=artifacts,
        execute=execute,
        promote=lambda: {},
        sanka=None,
        target="",
        max_turns=3,
        wall_seconds=120,
        max_output_tokens=args.max_output_tokens,
        max_context_bytes=args.max_context_bytes,
    )
    if managed:
        from sanka_bench.subscription import Subscription

        runner.history[0]["content"] = prompt.replace("Use exec", "Use bench_exec")
        prompt = runner.history[0]["content"]
        from sanka_bench.claude_subscription import ClaudeSubscription

        transport_class = ClaudeSubscription if args.provider == "anthropic" else Subscription
        with transport_class(
            runner.deadline, str(args.subscription_bin) if args.subscription_bin else None
        ) as transport:
            runner.exchange = transport
            outcome, stats = runner.run()
    else:
        outcome, stats = runner.run()
    probe = workspace / "probe.txt"
    checks = {
        "tool_use": probe.is_file()
        and not probe.is_symlink()
        and probe.read_text().strip() == nonce,
        "ordered_tool_results": stats["num_turns"] >= 2 and stats["work"]["tool_calls"] >= 1,
        "terminal_event": stats["subtype"] == "native-completed_unverified",
        "usage_accounting": stats["total_tokens"] is not None and stats["total_tokens"] > 0,
    }
    transcript = args.out.with_suffix(".jsonl")
    transcript.write_text(outcome.stdout)

    def digest(data: bytes) -> str:
        return "sha256:" + hashlib.sha256(data).hexdigest()

    evidence = {
        "schema": "sanka-bench/native-route-qualification/v1",
        "status": "qualified" if all(checks.values()) and not stats["is_error"] else "failed",
        "requested_model_id": args.model,
        "actual_model_id": args.actual_model_id or args.model,
        "provider": args.provider,
        "provider_variant": args.provider_variant,
        "route_kind": (
            "claude-managed-subscription"
            if args.provider == "anthropic"
            else "codex-managed-subscription"
        )
        if managed
        else "openai-responses"
        if args.provider == "openai"
        else "openai-chat",
        "billing_mode": args.billing_mode,
        "gateway_profile": None,
        "reasoning_effort": "high",
        "native": {
            "version": native_agent.version(),
            "sha256": digest(Path(native_agent.__file__).read_bytes()),
        },
        "checks": checks,
        "stats": stats,
        "evidence": {
            "prompt_sha256": digest(prompt.encode()),
            "provider_sha256": digest(native_agent.ROUTES[args.provider][0].encode()),
            "transcript_sha256": digest(transcript.read_bytes()),
        },
    }
    if managed and args.subscription_bin:
        evidence["subscription_bin_sha256"] = digest(args.subscription_bin.read_bytes())
    args.out.write_text(json.dumps(evidence, indent=2) + "\n")
    print(evidence["status"])
    return 0 if evidence["status"] == "qualified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
