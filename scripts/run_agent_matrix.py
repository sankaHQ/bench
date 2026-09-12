#!/usr/bin/env python3
"""Run a durable pass@1 agent matrix under one foreground coordinator.

The manifest owns cell identity, exact provider variant, commands, and paid-run
authorization. Workers own only cell artifacts. The coordinator is the single
aggregate writer and never retries or silently substitutes a provider.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from run_matrix_cell import ALLOWED_KEYS, evaluation_environment, read_allowlisted_env

from sanka_bench.environment import isolated_environment
from sanka_bench.hashing import digest_tree
from sanka_bench.schema import validate_candidate_id

_KNOWN_SECRET = re.compile(rb"(?<![A-Za-z0-9_])(?:sk-(?:ant-|proj-)?|fw_)[A-Za-z0-9_-]{16,}")


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def secret_hits(root: Path, secret_values: Sequence[str]) -> list[str]:
    """Return artifact paths containing credentials without returning credential text."""
    needles = {value.encode() for value in secret_values if len(value) >= 8}
    hits: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        content = path.read_bytes()
        if any(needle in content for needle in needles) or _KNOWN_SECRET.search(content):
            hits.append(path.relative_to(root).as_posix())
    return hits


def artifact_issues(root: Path, cells: Sequence[CellSpec]) -> list[str]:
    """Verify resumable cell evidence before publishing aggregate output."""
    issues: list[str] = []
    for cell in cells:
        if not cell.input_digest:  # v1 predates normalized cell telemetry
            continue
        state = cell_state(root, cell)
        label = cell.key
        if state == "untouched":
            continue
        if state == "ambiguous":
            issues.append(f"{label}: ambiguous cell artifacts")
            continue
        paths = artifacts(root, cell)
        marker = next(
            (line for line in reversed(marker_lines(paths.log)) if line.startswith("DRIVER_DONE ")),
            "",
        )
        successful_generation = state == "generated" or "run_exit=0" in marker

        telemetry_path = paths.candidate / "telemetry.json"
        transcript_path = paths.candidate / "agent-log.jsonl"
        raw_transcript_path = paths.sandbox / "raw" / "agent-log.jsonl"
        overlay = paths.candidate / "overlay"
        for name, path in (
            ("telemetry", telemetry_path),
            ("transcript", transcript_path),
            ("raw transcript", raw_transcript_path),
        ):
            if not path.is_file():
                issues.append(f"{label}: missing {name}")
        if successful_generation and not overlay.is_dir():
            issues.append(f"{label}: missing candidate overlay")
        if issues and any(issue.startswith(f"{label}: missing") for issue in issues):
            continue

        try:
            telemetry = load_json(telemetry_path)
        except (OSError, TypeError, json.JSONDecodeError):
            issues.append(f"{label}: invalid telemetry")
            continue
        if telemetry.get("schema") != "sanka-bench/agent-cell-telemetry/v1":
            issues.append(f"{label}: telemetry schema mismatch")
        if telemetry.get("input_digest") != cell.input_digest:
            issues.append(f"{label}: telemetry input digest mismatch")
        digests = telemetry.get("digests")
        if not isinstance(digests, dict):
            issues.append(f"{label}: missing telemetry digests")
            continue
        transcript_digest = "sha256:" + hashlib.sha256(transcript_path.read_bytes()).hexdigest()
        if digests.get("transcript_sha256") != transcript_digest:
            issues.append(f"{label}: transcript digest mismatch")
        if raw_transcript_path.read_bytes() != transcript_path.read_bytes():
            issues.append(f"{label}: raw transcript mismatch")
        if successful_generation and digests.get("overlay_sha256") != digest_tree(overlay):
            issues.append(f"{label}: overlay digest mismatch")

        if state != "terminal" or not successful_generation:
            continue
        try:
            report = load_json(paths.report)
        except (OSError, TypeError, json.JSONDecodeError):
            issues.append(f"{label}: invalid report")
            continue
        report_digest = "sha256:" + hashlib.sha256(paths.report.read_bytes()).hexdigest()
        evaluation = telemetry.get("evaluation")
        if not isinstance(evaluation, dict) or evaluation.get("report_sha256") != report_digest:
            issues.append(f"{label}: report digest mismatch")
        if not isinstance(evaluation, dict) or evaluation.get("status") != report.get("status"):
            issues.append(f"{label}: evaluation status mismatch")
        provenance = report.get("provenance")
        if not isinstance(provenance, dict) or provenance.get("candidate_digest") != digest_tree(
            paths.candidate
        ):
            issues.append(f"{label}: candidate digest mismatch")
    return issues


def credential_values(manifest: dict[str, Any]) -> list[str]:
    names = {name for name in ALLOWED_KEYS if name.endswith(("_KEY", "_TOKEN"))}
    values = [os.environ[name] for name in names if os.environ.get(name)]
    raw_path = str(manifest.get("toolchain", {}).get("env_path") or "")
    if raw_path and not raw_path.startswith("PENDING_"):
        path = Path(raw_path).expanduser()
        if path.is_file():
            values.extend(
                value for name, value in read_allowlisted_env(path).items() if name in names
            )
    return values


@dataclass(frozen=True)
class CellSpec:
    task: str
    task_suffix: str
    model_slug: str
    candidate_slug: str
    provider: str
    provider_variant: str
    harness: str
    requested_model_id: str
    actual_model_id: str
    route_kind: str
    billing_mode: str
    gateway_profile: str | None
    input_digest: str
    config: str
    route_weight: int
    sample: int = 1
    samples: int = 1

    @property
    def candidate_id(self) -> str:
        """Cell identity; samples beyond the first run carry ``-s<k>`` (report groups them)."""
        base = f"{self.task}-{self.candidate_slug}-{self.config}"
        return f"{base}-s{self.sample}" if self.samples > 1 else base

    @property
    def key(self) -> str:
        base = f"{self.task}:{self.model_slug}:{self.config}"
        return f"{base}:s{self.sample}" if self.samples > 1 else base


@dataclass(frozen=True)
class CellArtifacts:
    candidate: Path
    report: Path
    log: Path
    sandbox: Path


@dataclass
class StageResult:
    stage_id: str
    requested: int
    completed: int = 0
    terminal_skipped: int = 0
    stopped_before_generation: int = 0
    generation_failures: int = 0
    evaluation_failures: int = 0
    drained_evaluations: int = 0
    retried_generations: int = 0
    max_generation_total: int = 0
    max_evaluations: int = 0
    max_generation_by_provider: dict[str, int] | None = None
    max_generation_by_model: dict[str, int] | None = None
    elapsed_seconds: float = 0.0

    @property
    def failures(self) -> int:
        return self.generation_failures + self.evaluation_failures

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage_id": self.stage_id,
            "requested": self.requested,
            "completed": self.completed,
            "terminal_skipped": self.terminal_skipped,
            "stopped_before_generation": self.stopped_before_generation,
            "generation_failures": self.generation_failures,
            "evaluation_failures": self.evaluation_failures,
            "failures": self.failures,
            "drained_evaluations": self.drained_evaluations,
            "retried_generations": self.retried_generations,
            "max_generation_total": self.max_generation_total,
            "max_evaluations": self.max_evaluations,
            "max_generation_by_provider": dict(self.max_generation_by_provider or {}),
            "max_generation_by_model": dict(self.max_generation_by_model or {}),
            "elapsed_seconds": round(self.elapsed_seconds, 3),
        }


def cell_input_digest(
    manifest: dict[str, Any],
    *,
    task: str,
    model: dict[str, Any],
    config: str,
    sample: int,
) -> str:
    execution_fields = (
        "max_turns",
        "max_output_tokens",
        "max_context_bytes",
        "max_agent_cost_usd",
        "wall_clock_seconds",
        "prompt_sha256",
        "sanka_prompt_sha256",
        "sanka_workflow",
        "sanka_readiness_threshold",
        "authorization_scope",
        "concurrency",
        "container_engine",
    )
    toolchain_fields = (
        "claude_version",
        "claude_bin_sha256",
        "native_version",
        "native_bin_sha256",
        "codex_version",
        "codex_bin_sha256",
        "agent_runner_sha256",
        "evaluator_sha256",
        "sanka_cli",
        "extension_version",
        "sanka_skill_sha256",
    )
    toolchain = manifest.get("toolchain", {})
    payload = {
        "benchmark_sha": manifest["benchmark_sha"],
        "cell": {"task": task, "config": config, "sample": sample},
        "model": model,
        "execution": {
            key: manifest["execution"].get(key)
            for key in execution_fields
            if key in manifest["execution"]
        },
        "toolchain": {key: toolchain.get(key) for key in toolchain_fields if key in toolchain},
    }
    if "experimental_toolchain" in manifest:
        payload["experimental_toolchain"] = manifest["experimental_toolchain"]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def build_cells(manifest: dict[str, Any]) -> list[CellSpec]:
    cells: list[CellSpec] = []
    weights = manifest["suite"]["route_weights"]
    configurations = manifest["execution"]["configurations"]
    samples = int(manifest["execution"].get("samples", 1))
    if samples < 1:
        raise ValueError("execution.samples must be a positive integer")
    for task in manifest["suite"]["tasks"]:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", str(task)):
            raise ValueError(f"unsafe task slug: {task}")
        suffix = str(task).rsplit("-", 1)[-1]
        for model in manifest["models"]:
            for label in ("slug", "candidate_slug"):
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", str(model[label])):
                    raise ValueError(f"unsafe model {label}: {model[label]}")
            variant = str(model.get("provider_variant") or "standard")
            for config in configurations:
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", str(config)):
                    raise ValueError(f"unsafe configuration slug: {config}")
                for sample in range(1, samples + 1):
                    cells.append(
                        CellSpec(
                            task=str(task),
                            task_suffix=suffix,
                            model_slug=str(model["slug"]),
                            candidate_slug=str(model["candidate_slug"]),
                            provider=str(model["provider"]),
                            provider_variant=variant,
                            harness=str(model.get("harness") or model.get("agent") or ""),
                            requested_model_id=str(
                                model.get("requested_model_id") or model.get("model_id") or ""
                            ),
                            actual_model_id=str(
                                model.get("actual_model_id")
                                or model.get("requested_model_id")
                                or model.get("model_id")
                                or ""
                            ),
                            route_kind=str(model.get("route_kind") or "legacy"),
                            billing_mode=str(model.get("billing_mode") or "unknown"),
                            gateway_profile=(
                                str(model["gateway_profile"])
                                if model.get("gateway_profile") is not None
                                else None
                            ),
                            input_digest=(
                                cell_input_digest(
                                    manifest,
                                    task=str(task),
                                    model=model,
                                    config=str(config),
                                    sample=sample,
                                )
                                if manifest.get("schema")
                                == "sanka-bench/model-matrix-run-manifest/v2"
                                else ""
                            ),
                            config=str(config),
                            route_weight=int(weights[task]),
                            sample=sample,
                            samples=samples,
                        )
                    )
    for cell in cells:
        validate_candidate_id(cell.candidate_id)
    expected = int(manifest["execution"]["expected_rows"])
    if len(cells) != expected:
        raise ValueError(f"manifest expands to {len(cells)} cells, expected {expected}")
    if len({cell.key for cell in cells}) != len(cells):
        raise ValueError("manifest expands to duplicate cell keys")
    if len({cell.candidate_id for cell in cells}) != len(cells):
        raise ValueError("manifest expands to duplicate artifact paths")
    return cells


def qualification_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def validate_official_manifest(manifest: dict[str, Any], root: Path) -> None:
    if manifest.get("schema") != "sanka-bench/model-matrix-run-manifest/v2":
        return
    lanes = {str(task).rsplit("-", 1)[0] for task in manifest["suite"]["tasks"]}
    if len(lanes) != 1 or not lanes <= {"drf-fastapi", "drf-flask"}:
        raise ValueError(
            "official v2 comparisons require one supported migration lane per manifest"
        )
    if manifest["execution"].get("configurations") not in (
        ["alone", "with-sanka"],
        ["alone", "sanka-cli"],
        ["alone", "sanka-cli", "with-sanka"],
    ):
        raise ValueError(
            "official v2 configurations must be alone paired with sanka-cli or with-sanka, "
            "or the three-arm ablation"
        )
    if any(
        not isinstance(manifest["execution"].get(name), int)
        or isinstance(manifest["execution"].get(name), bool)
        or manifest["execution"][name] < 1
        for name in ("max_turns", "wall_clock_seconds")
    ):
        raise ValueError("official v2 manifest requires positive execution budgets")
    cost_limit = manifest["execution"].get("max_agent_cost_usd")
    for name in ("max_output_tokens", "max_context_bytes"):
        value = manifest["execution"].get(name)
        if value is not None and (
            type(value) is not int
            or value <= 0
            or any(model.get("harness") != "sanka-native" for model in manifest["models"])
        ):
            raise ValueError(f"{name} requires native models and a positive integer")
    if cost_limit is not None and (
        isinstance(cost_limit, bool)
        or not isinstance(cost_limit, int | float)
        or not math.isfinite(cost_limit)
        or cost_limit <= 0
    ):
        raise ValueError("max_agent_cost_usd must be finite and positive")
    if manifest["execution"].get("container_engine", "docker") not in {"docker", "podman"}:
        raise ValueError("official v2 manifest container engine must be docker or podman")
    workflow = manifest["execution"].get("sanka_workflow", "availability-v1")
    threshold = manifest["execution"].get("sanka_readiness_threshold", 0.5)
    if workflow not in {
        "availability-v1",
        "artifacts-first-v1",
        "artifacts-first-v2",
        "native-lifecycle-v1",
    }:
        raise ValueError("unknown Sanka workflow")
    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, int | float)
        or not 0 <= threshold <= 1
    ):
        raise ValueError("Sanka readiness threshold must be between 0 and 1")
    concurrency = manifest["execution"].get("concurrency")
    if not isinstance(concurrency, dict) or any(
        not isinstance(concurrency.get(name), int)
        or isinstance(concurrency.get(name), bool)
        or concurrency[name] < 1
        for name in ("provider_cap", "model_cap", "evaluation_cap")
    ):
        raise ValueError("official v2 manifest requires positive concurrency pins")
    toolchain = manifest.get("toolchain")
    if not isinstance(toolchain, dict):
        raise ValueError("official v2 manifest requires toolchain pins")
    skill_sha = toolchain.get("sanka_skill_sha256")
    if re.fullmatch(r"sha256:[0-9a-f]{64}", str(skill_sha or "")) is None:
        raise ValueError("official v2 manifest requires Sanka skill pins")
    root = root.resolve()
    for model in manifest["models"]:
        harness = model.get("harness")
        if workflow == "native-lifecycle-v1" and harness != "sanka-native":
            raise ValueError("native-lifecycle-v1 requires the native harness")
        if harness not in {"claude-code", "codex", "sanka-native"}:
            raise ValueError("official v2 matrices require a supported pinned harness")
        agent_tool = {"claude-code": "claude", "codex": "codex", "sanka-native": "native"}[harness]
        agent_version = toolchain.get(f"{agent_tool}_version")
        agent_sha = toolchain.get(f"{agent_tool}_bin_sha256")
        if (
            not isinstance(agent_version, str)
            or not agent_version
            or re.fullmatch(r"sha256:[0-9a-f]{64}", str(agent_sha or "")) is None
        ):
            raise ValueError(f"official v2 manifest requires {agent_tool} version and binary pins")
        if harness == "sanka-native":
            managed = (
                model.get("provider") == "openai" and model.get("billing_mode") == "subscription"
            )
            expected_route = (
                "codex-managed-subscription"
                if managed
                else {"openai": "openai-responses", "fireworks": "openai-chat"}.get(
                    model.get("provider")
                )
            )
            model_cost_limit = model.get("max_agent_cost_usd", cost_limit)
            if model_cost_limit is not None and (
                type(model_cost_limit) not in {int, float}
                or not math.isfinite(model_cost_limit)
                or model_cost_limit <= 0
            ):
                raise ValueError("model cost limit must be positive and finite")
            if managed and model_cost_limit is not None:
                raise ValueError("subscription matrices cannot use API dollar caps")
            if (
                expected_route is None
                or model.get("route_kind") != expected_route
                or model.get("billing_mode") != ("subscription" if managed else "api_key")
                or model.get("gateway_profile") is not None
                or model.get("reasoning_effort") != "high"
            ):
                raise ValueError(
                    "native matrices require a qualified API or managed subscription route "
                    "and high reasoning"
                )
            if manifest["execution"].get("sanka_workflow") != "native-lifecycle-v1":
                raise ValueError("native matrices require native-lifecycle-v1")
            if model_cost_limit is not None and any(
                type(model.get(name)) not in {int, float}
                or not math.isfinite(model[name])
                or model[name] < 0
                for name in ("price_in", "price_out")
            ):
                raise ValueError("native cost cap requires finite provider prices")
            cached = model.get("price_cached")
            if cached is not None and (
                type(cached) not in {int, float}
                or not math.isfinite(cached)
                or type(model.get("price_in")) not in {int, float}
                or not math.isfinite(model["price_in"])
                or not 0 <= cached <= model["price_in"]
            ):
                raise ValueError("price_cached must be finite and between zero and price_in")
        if harness == "codex":
            if (
                model.get("provider") != "openai"
                or model.get("route_kind") != "openai-responses"
                or model.get("billing_mode") != "api_key"
                or model.get("gateway_profile") is not None
            ):
                raise ValueError("Codex official matrices require OpenAI Responses API-key billing")
            if model.get("reasoning_effort") not in {
                "none",
                "low",
                "medium",
                "high",
                "xhigh",
                "max",
            }:
                raise ValueError("Codex official matrices require explicit reasoning effort")
            if cost_limit is not None:
                raise ValueError("max_agent_cost_usd is a Claude-only limit")
        route_kind = model.get("route_kind")
        billing_mode = model.get("billing_mode")
        gateway_profile = model.get("gateway_profile")
        if harness == "sanka-native" or (route_kind == "openai-responses" and harness == "codex"):
            pass
        elif route_kind == "anthropic-native":
            if billing_mode != "subscription" or gateway_profile is not None:
                raise ValueError(
                    "anthropic-native routes require subscription billing and no gateway profile"
                )
        elif route_kind == "gateway":
            if billing_mode != "api_key" or not gateway_profile:
                raise ValueError("gateway routes require api_key billing and a gateway profile")
        else:
            raise ValueError("route_kind must be anthropic-native or gateway")

        path = (root / str(model.get("qualification") or "")).resolve()
        if not path.is_relative_to(root):
            raise ValueError("qualification path escapes the run directory")
        expected_digest = model.get("qualification_sha256")
        if not path.is_file() or qualification_digest(path) != expected_digest:
            raise ValueError("qualification digest does not match the manifest")
        evidence = load_json(path)
        if (
            evidence.get("schema") != f"sanka-bench/{agent_tool}-route-qualification/v1"
            or evidence.get("status") != "qualified"
        ):
            raise ValueError("qualification record is not qualified")
        if model.get("route_kind") == "codex-managed-subscription":
            pin = toolchain.get("subscription_bin_sha256")
            if (
                re.fullmatch(r"sha256:[0-9a-f]{64}", str(pin or "")) is None
                or evidence.get("subscription_bin_sha256") != pin
            ):
                raise ValueError("subscription qualification binary pin mismatch")
        checks = evidence.get("checks")
        required_checks = (
            "tool_use",
            "terminal_event",
            "usage_accounting",
            "ordered_tool_results" if harness == "sanka-native" else "streaming",
        )
        if not isinstance(checks, dict) or any(
            checks.get(name) is not True for name in required_checks
        ):
            raise ValueError("qualification checks are incomplete")
        agent_evidence = evidence.get(agent_tool)
        if not isinstance(agent_evidence, dict) or (
            agent_evidence.get("version") != agent_version
            or agent_evidence.get("sha256") != agent_sha
        ):
            raise ValueError(
                f"qualification {agent_tool.title()} harness evidence does not match the manifest"
            )
        hashes = evidence.get("evidence")
        if not isinstance(hashes, dict) or any(
            re.fullmatch(r"sha256:[0-9a-f]{64}", str(hashes.get(name) or "")) is None
            for name in ("prompt_sha256", "provider_sha256", "transcript_sha256")
        ):
            raise ValueError("qualification evidence hashes are incomplete")
        transcript = path.with_suffix(".jsonl")
        if (
            not transcript.is_file()
            or qualification_digest(transcript) != hashes["transcript_sha256"]
        ):
            raise ValueError("qualification transcript digest does not match its evidence")
        if (
            harness == "sanka-native"
            and evidence.get("reasoning_effort") != model["reasoning_effort"]
        ):
            raise ValueError("qualification reasoning effort does not match the manifest")
        if harness == "codex":
            if evidence.get("reasoning_effort") != model["reasoning_effort"]:
                raise ValueError("qualification reasoning effort does not match the manifest")
            session = path.with_suffix(".session.jsonl")
            if not session.is_file() or qualification_digest(session) != hashes.get(
                "session_sha256"
            ):
                raise ValueError("qualification session digest mismatch")
            contexts = [
                event["payload"]
                for line in session.read_text().splitlines()
                if (event := json.loads(line)).get("type") == "turn_context"
            ]
            if not contexts or any(
                c.get("model") != model["actual_model_id"]
                or c.get("effort") != model["reasoning_effort"]
                for c in contexts
            ):
                raise ValueError("qualification session model or reasoning mismatch")
        for field in (
            "requested_model_id",
            "actual_model_id",
            "provider",
            "provider_variant",
            "route_kind",
            "billing_mode",
            "gateway_profile",
        ):
            if evidence.get(field) != model.get(field):
                label = field.replace("_", " ")
                raise ValueError(f"qualification {label} does not match the manifest")


def validate_backups(manifest: dict[str, Any]) -> None:
    for model in manifest["models"]:
        variant = str(model.get("provider_variant") or "standard")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", variant):
            raise ValueError(f"invalid provider_variant for {model['slug']}")
        for backup in model.get("backups", []):
            required = {
                "label",
                "provider",
                "provider_variant",
                "model_id",
                "wire_api",
                "adapter",
                "status",
            }
            missing = sorted(required - set(backup))
            if missing:
                raise ValueError(f"backup for {model['slug']} is missing: {', '.join(missing)}")
            backup_variant = str(backup["provider_variant"])
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", backup_variant):
                raise ValueError(f"invalid backup provider_variant for {model['slug']}")
            if backup["status"] not in {"unqualified", "qualified"}:
                raise ValueError("backup status must be unqualified or qualified")
            if backup["status"] == "qualified" and not backup.get("qualification_evidence"):
                raise ValueError("qualified backup requires qualification_evidence")


def worktree_preflight(manifest: dict[str, Any]) -> dict[str, str]:
    raw = str(manifest.get("toolchain", {}).get("worktree") or "")
    expected = str(manifest.get("benchmark_sha") or "")
    if not raw or not re.fullmatch(r"[0-9a-f]{40}", expected):
        raise ValueError("toolchain.worktree and an exact benchmark_sha are required")
    worktree = Path(raw).resolve()
    actual = subprocess.check_output(
        ["git", "-C", str(worktree), "rev-parse", "HEAD"],
        text=True,
        env=isolated_environment(os.environ),
    ).strip()
    if actual != expected:
        raise ValueError(f"worktree SHA mismatch: expected {expected}, got {actual}")
    status = subprocess.run(
        [
            "git",
            "-C",
            str(worktree),
            "status",
            "--porcelain",
            "--untracked-files=no",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=isolated_environment(os.environ),
    )
    if status.returncode != 0 or status.stdout.strip():
        raise ValueError("benchmark worktree has tracked changes")
    return {"worktree": str(worktree), "benchmark_sha": actual}


def artifacts(root: Path, cell: CellSpec) -> CellArtifacts:
    return CellArtifacts(
        candidate=root / "candidates" / cell.task / cell.candidate_id,
        report=root / "reports" / f"{cell.task}-{cell.candidate_id}.json",
        log=root / "logs" / f"run-{cell.task_suffix}-{cell.candidate_id}.log",
        sandbox=root / "sandboxes" / cell.candidate_id,
    )


def marker_lines(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def cell_state(root: Path, cell: CellSpec) -> str:
    paths = artifacts(root, cell)
    lines = marker_lines(paths.log)
    if cell.input_digest and (
        paths.log.exists()
        or paths.candidate.exists()
        or paths.report.exists()
        or paths.sandbox.exists()
    ):
        recorded = [
            line.removeprefix("INPUT_DIGEST=") for line in lines if line.startswith("INPUT_DIGEST=")
        ]
        if recorded != [cell.input_digest]:
            return "ambiguous"
    driver_lines = [line for line in lines if line.startswith("DRIVER_DONE ")]
    if driver_lines:
        marker = driver_lines[-1]
        run_match = re.search(r"(?:^| )run_exit=([^ ]+)", marker)
        eval_match = re.search(r"(?:^| )eval_exit=([^ ]+)", marker)
        if run_match is None or eval_match is None:
            return "ambiguous"
        run_exit = run_match.group(1)
        eval_exit = eval_match.group(1)
        if run_exit == "0":
            if not paths.candidate.is_dir() or not paths.report.is_file():
                return "ambiguous"
            if eval_exit == "skipped":
                return "ambiguous"
        elif paths.report.exists() or eval_exit != "skipped":
            return "ambiguous"
        return "terminal"
    if any(line.startswith("GENERATION_DONE run_exit=0 ") for line in lines):
        if not paths.candidate.is_dir() or paths.report.exists():
            return "ambiguous"
        return "generated"
    if (
        paths.log.exists()
        or paths.candidate.exists()
        or paths.report.exists()
        or paths.sandbox.exists()
    ):
        return "ambiguous"
    return "untouched"


RETRYABLE_MARKER = "agent reported an error"


def retryable_failure(manifest: dict[str, Any], root: Path, cell: CellSpec) -> str | None:
    """Return the disclosed reason when a failed generation may be retried once.

    Only provider-side incidents qualify: the driver log's agent error must match one of
    ``execution.auto_retry.patterns`` (capacity, rate limits, transient 5xx), the cell must
    not have been retried before, and the failed attempt must have produced no candidate
    overlay — i.e. no model output that a second attempt could be "retrying into shape".
    Quality failures never come through here: they end with a candidate and a report.
    """
    policy = manifest["execution"].get("auto_retry")
    if not isinstance(policy, dict):
        return None
    patterns = [str(item) for item in policy.get("patterns", [])]
    if not patterns:
        return None
    if cell.candidate_id in manifest["execution"].get("infrastructure_retries", {}):
        return None
    paths = artifacts(root, cell)
    overlay = paths.candidate / "overlay"
    if overlay.exists() and any(overlay.rglob("*")):
        return None
    errors = [line for line in marker_lines(paths.log) if line.startswith(RETRYABLE_MARKER)]
    if not errors:
        return None
    reason = errors[-1][len(RETRYABLE_MARKER) :].strip(" :")
    lowered = reason.lower()
    if not any(pattern.lower() in lowered for pattern in patterns):
        return None
    return reason[:400]


def authorize_retry(
    manifest_path: Path, manifest: dict[str, Any], root: Path, cell: CellSpec, reason: str
) -> Path:
    """Move attempt 1 into an incident ledger and authorize attempt 2 in the manifest.

    This is the same protocol an operator follows by hand after a halt: the failed
    attempt's log and candidate directory become the ledger, ``incident.json`` records the
    evidence, and ``execution.infrastructure_retries`` carries the attempt-2 authorization
    that the cell driver turns into ``--attempt 2 --prior-failure`` so GENERATED.md
    discloses the retry.
    """
    paths = artifacts(root, cell)
    incident = root / "incidents" / "auto-retry" / cell.candidate_id
    attempt_dir = incident / "attempt-1"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    evidence = [line for line in marker_lines(paths.log) if not line.startswith("RUN_START")]
    if paths.log.exists():
        shutil.move(str(paths.log), str(attempt_dir / paths.log.name))
    if paths.candidate.exists():
        shutil.move(str(paths.candidate), str(attempt_dir / "candidate"))
    if paths.sandbox.exists():
        shutil.move(str(paths.sandbox), str(attempt_dir / "sandbox"))
    ledger = incident / "incident.json"
    atomic_json(
        ledger,
        {
            "cell": cell.key,
            "candidate_id": cell.candidate_id,
            "recorded_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "classification": "infrastructure: provider incident matched execution.auto_retry",
            "reason": reason,
            "evidence": evidence[-12:],
            "authorized_retry_scope": "this cell only, attempt 2, same treatment",
        },
    )
    retries = manifest["execution"].setdefault("infrastructure_retries", {})
    retries[cell.candidate_id] = {
        "attempt": 2,
        "prior_failure": reason,
        "authorization_ledger": ledger.relative_to(root).as_posix(),
    }
    atomic_json(manifest_path, manifest)
    return ledger


def prioritized(
    root: Path, cells: Iterable[CellSpec], *, matrix_cells: Iterable[CellSpec] | None = None
) -> list[CellSpec]:
    cells = list(cells)
    reference = cells if matrix_cells is None else list(matrix_cells)
    states = {cell.key: cell_state(root, cell) for cell in cells}
    configurations = list(dict.fromkeys(cell.config for cell in reference))
    pairs: dict[tuple[str, int], int] = {}
    for cell in reference:
        pairs.setdefault((cell.task, cell.sample), len(pairs))

    def lane_rank(cell: CellSpec) -> int:
        pair = pairs[(cell.task, cell.sample)]
        return (configurations.index(cell.config) - pair) % len(configurations)

    return sorted(
        cells,
        key=lambda cell: (
            0 if states[cell.key] == "generated" else 1,
            -cell.route_weight,
            cell.provider,
            cell.model_slug,
            cell.task,
            cell.sample,
            lane_rank(cell),
        ),
    )


def render_command(
    template: list[str], manifest_path: Path, cell: CellSpec, phase: str
) -> list[str]:
    values = {
        "python": sys.executable,
        "manifest": str(manifest_path),
        "phase": phase,
        "task": cell.task,
        "task_suffix": cell.task_suffix,
        "model": cell.model_slug,
        "config": cell.config,
        "provider": cell.provider,
        "provider_variant": cell.provider_variant,
        "sample": str(cell.sample),
        "candidate_id": cell.candidate_id,
    }
    return [str(item).format_map(values) for item in template]


@contextmanager
def coordinator_lock(root: Path, manifest: dict[str, Any]):
    path = root / ".agent-matrix-coordinator.lock"
    authorization = manifest["authorization"]
    payload = {
        "schema": "sanka-bench/agent-matrix-lock/v1",
        "pid": os.getpid(),
        "benchmark_sha": manifest["benchmark_sha"],
        "run_id": authorization["run_id"],
        "acquired_at": utc_now(),
    }
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ValueError(f"coordinator lock requires inspection: {path}") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        yield
    finally:
        if path.exists():
            current = load_json(path)
            if current.get("pid") == os.getpid() and current.get("run_id") == payload["run_id"]:
                path.unlink()


class Activity:
    def __init__(self) -> None:
        self.generation_total = 0
        self.evaluations = 0
        self.generation_by_provider: dict[str, int] = defaultdict(int)
        self.generation_by_model: dict[str, int] = defaultdict(int)
        self.max_generation_total = 0
        self.max_evaluations = 0
        self.max_generation_by_provider: dict[str, int] = defaultdict(int)
        self.max_generation_by_model: dict[str, int] = defaultdict(int)
        self.lock = asyncio.Lock()

    async def generation_started(self, cell: CellSpec) -> None:
        async with self.lock:
            self.generation_total += 1
            self.generation_by_provider[cell.provider] += 1
            self.generation_by_model[cell.model_slug] += 1
            self.max_generation_total = max(self.max_generation_total, self.generation_total)
            self.max_generation_by_provider[cell.provider] = max(
                self.max_generation_by_provider[cell.provider],
                self.generation_by_provider[cell.provider],
            )
            self.max_generation_by_model[cell.model_slug] = max(
                self.max_generation_by_model[cell.model_slug],
                self.generation_by_model[cell.model_slug],
            )

    async def generation_finished(self, cell: CellSpec) -> None:
        async with self.lock:
            self.generation_total -= 1
            self.generation_by_provider[cell.provider] -= 1
            self.generation_by_model[cell.model_slug] -= 1

    async def evaluation_started(self) -> None:
        async with self.lock:
            self.evaluations += 1
            self.max_evaluations = max(self.max_evaluations, self.evaluations)

    async def evaluation_finished(self) -> None:
        async with self.lock:
            self.evaluations -= 1


class RollingCoordinator:
    def __init__(
        self,
        manifest_path: Path,
        *,
        provider_cap: int,
        model_cap: int,
        evaluation_cap: int,
    ) -> None:
        self.manifest_path = manifest_path.resolve()
        self.root = self.manifest_path.parent
        self.manifest = load_json(self.manifest_path)
        validate_official_manifest(self.manifest, self.root)
        validate_backups(self.manifest)
        self.cells = build_cells(self.manifest)
        if self.manifest.get("schema") == "sanka-bench/model-matrix-run-manifest/v2":
            pinned = self.manifest["execution"]["concurrency"]
            requested = {
                "provider_cap": provider_cap,
                "model_cap": model_cap,
                "evaluation_cap": evaluation_cap,
            }
            if requested != pinned:
                raise ValueError(f"CLI concurrency does not match pinned concurrency: {pinned}")
        self.provider_cap = provider_cap
        self.model_cap = model_cap
        self.evaluation_cap = evaluation_cap
        self.events = self.root / "scheduler-events.jsonl"
        self.stop_generation: asyncio.Event | None = None
        self.processes: set[asyncio.subprocess.Process] = set()
        self.activity: Activity | None = None
        self.provider_semaphores: dict[str, asyncio.Semaphore] = {}
        self.model_semaphores: dict[str, asyncio.Semaphore] = {}
        self.evaluation_semaphore: asyncio.Semaphore | None = None
        self.stage_concurrency = 1

    def event(self, kind: str, **fields: Any) -> None:
        value = {"at": utc_now(), "event": kind, **fields}
        self.events.parent.mkdir(parents=True, exist_ok=True)
        with self.events.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(value, sort_keys=True) + "\n")

    async def terminate_owned(self) -> None:
        for process in list(self.processes):
            if process.returncode is None:
                process.terminate()
        if self.processes:
            await asyncio.gather(
                *(process.wait() for process in list(self.processes)),
                return_exceptions=True,
            )

    async def _process(self, cell: CellSpec, phase: str, stage_id: str) -> int:
        template = self.manifest["execution"]["cell_command"]
        if not isinstance(template, list) or not all(isinstance(item, str) for item in template):
            raise ValueError("execution.cell_command must be a string list")
        command = render_command(template, self.manifest_path, cell, phase)
        worker_log = self.root / "waves" / f"{stage_id}-{cell.candidate_id}-{phase}.log"
        worker_log.parent.mkdir(parents=True, exist_ok=True)
        environment = (
            evaluation_environment(self.manifest)
            if phase == "evaluate"
            else isolated_environment(os.environ, ("SANKA_BENCH_CELL_COST_CAP_USD",))
        )
        environment.update(
            {
                "SANKA_BENCH_WAVE_ID": stage_id,
                "SANKA_BENCH_WAVE_CONCURRENCY": str(self.stage_concurrency),
                "SANKA_BENCH_TIMING_METHODOLOGY": "rolling-provider-queue",
                "SANKA_BENCH_COORDINATOR_RUN_ID": str(self.manifest["authorization"]["run_id"]),
                "SANKA_BENCH_INPUT_DIGEST": cell.input_digest,
            }
        )
        with worker_log.open("wb") as handle:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=self.root,
                env=environment,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=handle,
                stderr=asyncio.subprocess.STDOUT,
            )
            self.processes.add(process)
            try:
                return await process.wait()
            except asyncio.CancelledError:
                if process.returncode is None:
                    process.terminate()
                    await process.wait()
                raise
            finally:
                self.processes.discard(process)

    async def _run_cell(self, cell: CellSpec, stage_id: str, result: StageResult) -> None:
        assert self.stop_generation is not None
        assert self.activity is not None
        assert self.evaluation_semaphore is not None
        state = cell_state(self.root, cell)
        if state == "terminal":
            result.terminal_skipped += 1
            return
        if state == "ambiguous":
            result.generation_failures += 1
            self.stop_generation.set()
            self.event("ambiguous-cell", stage_id=stage_id, cell=cell.key)
            return

        if state == "untouched":
            provider = self.provider_semaphores[cell.provider]
            model = self.model_semaphores[cell.model_slug]
            async with provider, model:
                if self.stop_generation.is_set():
                    result.stopped_before_generation += 1
                    return
                for attempt in (1, 2):
                    await self.activity.generation_started(cell)
                    self.event(
                        "generation-start",
                        stage_id=stage_id,
                        cell=cell.key,
                        provider_variant=cell.provider_variant,
                        attempt=attempt,
                    )
                    try:
                        returncode = await self._process(cell, "generate", stage_id)
                    finally:
                        await self.activity.generation_finished(cell)
                    self.event(
                        "generation-end",
                        stage_id=stage_id,
                        cell=cell.key,
                        returncode=returncode,
                        attempt=attempt,
                    )
                    if returncode == 0:
                        break
                    reason = (
                        retryable_failure(self.manifest, self.root, cell) if attempt == 1 else None
                    )
                    if reason is None:
                        result.generation_failures += 1
                        self.stop_generation.set()
                        return
                    ledger = authorize_retry(
                        self.manifest_path, self.manifest, self.root, cell, reason
                    )
                    result.retried_generations += 1
                    self.event(
                        "generation-retry",
                        stage_id=stage_id,
                        cell=cell.key,
                        reason=reason,
                        ledger=ledger.relative_to(self.root).as_posix(),
                    )
                    backoff = float(
                        self.manifest["execution"]["auto_retry"].get("backoff_seconds", 60)
                    )
                    await asyncio.sleep(backoff)

        # A provider failure stops new paid generations, but every already
        # generated pass@1 candidate is still immutable evidence. Drain those
        # evaluations so successful paid work is not stranded or regenerated.
        draining = self.stop_generation.is_set()
        async with self.evaluation_semaphore:
            await self.activity.evaluation_started()
            self.event("evaluation-start", stage_id=stage_id, cell=cell.key, draining=draining)
            try:
                returncode = await self._process(cell, "evaluate", stage_id)
            finally:
                await self.activity.evaluation_finished()
            self.event(
                "evaluation-end",
                stage_id=stage_id,
                cell=cell.key,
                returncode=returncode,
                draining=draining,
            )
            if returncode != 0:
                result.evaluation_failures += 1
                self.stop_generation.set()
                return
        if draining or self.stop_generation.is_set():
            result.drained_evaluations += 1
        result.completed += 1

    def aggregate(self, stage_id: str) -> int:
        template = self.manifest["execution"].get("aggregate_command")
        if self.manifest["execution"].get("sanka_workflow") in {
            "artifacts-first-v1",
            "artifacts-first-v2",
        }:
            from matrix_report import write_report

            try:
                write_report(self.manifest, self.root)
            except ValueError as exc:
                self.event("publication-gate-failed", stage_id=stage_id, error=str(exc))
                return 22
        if not template:
            return 0
        secrets = secret_hits(self.root, credential_values(self.manifest))
        integrity = artifact_issues(self.root, self.cells)
        if secrets or integrity:
            self.event(
                "publication-gate-failed",
                stage_id=stage_id,
                secret_paths=secrets,
                artifact_issues=integrity,
            )
            return 22
        if not isinstance(template, list) or not all(isinstance(item, str) for item in template):
            raise ValueError("execution.aggregate_command must be a string list")
        command = [sys.executable if item == "{python}" else item for item in template]
        path = self.root / "waves" / f"{stage_id}.aggregate.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as handle:
            outcome = subprocess.run(
                command,
                cwd=self.root,
                stdin=subprocess.DEVNULL,
                stdout=handle,
                stderr=subprocess.STDOUT,
                check=False,
                env=isolated_environment(os.environ),
            )
        return outcome.returncode

    async def run_stage(self, stage_id: str, cells: list[CellSpec]) -> StageResult:
        self.stop_generation = asyncio.Event()
        self.activity = Activity()
        self.provider_semaphores = {
            provider: asyncio.Semaphore(self.provider_cap)
            for provider in {cell.provider for cell in self.cells}
        }
        self.model_semaphores = {
            model: asyncio.Semaphore(self.model_cap)
            for model in {cell.model_slug for cell in self.cells}
        }
        self.evaluation_semaphore = asyncio.Semaphore(self.evaluation_cap)
        result = StageResult(stage_id=stage_id, requested=len(cells))
        providers = len({cell.provider for cell in cells})
        self.stage_concurrency = min(len(cells), self.provider_cap * providers)
        started = time.monotonic()
        self.event(
            "stage-start",
            stage_id=stage_id,
            requested=len(cells),
            provider_cap=self.provider_cap,
            model_cap=self.model_cap,
            evaluation_cap=self.evaluation_cap,
        )
        tasks = [
            asyncio.create_task(self._run_cell(cell, stage_id, result))
            for cell in prioritized(self.root, cells, matrix_cells=self.cells)
        ]
        loop = asyncio.get_running_loop()
        current = asyncio.current_task()
        installed: list[signal.Signals] = []
        if current is not None:
            for interrupt in (signal.SIGTERM, signal.SIGHUP):
                try:
                    loop.add_signal_handler(interrupt, current.cancel)
                    installed.append(interrupt)
                except (NotImplementedError, RuntimeError):
                    pass
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            self.stop_generation.set()
            for task in tasks:
                task.cancel()
            await self.terminate_owned()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        except Exception:
            self.stop_generation.set()
            for task in tasks:
                task.cancel()
            await self.terminate_owned()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        finally:
            for interrupt in installed:
                loop.remove_signal_handler(interrupt)
        result.elapsed_seconds = time.monotonic() - started
        result.max_generation_total = self.activity.max_generation_total
        result.max_evaluations = self.activity.max_evaluations
        result.max_generation_by_provider = dict(self.activity.max_generation_by_provider)
        result.max_generation_by_model = dict(self.activity.max_generation_by_model)
        wave_path = self.root / "waves" / f"{stage_id}.json"
        atomic_json(wave_path, result.as_dict())
        if self.aggregate(stage_id) != 0:
            result.evaluation_failures += 1
            atomic_json(wave_path, result.as_dict())
        self.event("stage-end", **result.as_dict())
        return result


def ensure_authorized(manifest: dict[str, Any]) -> None:
    authorization = manifest.get("authorization", {})
    expected_scope = manifest["execution"].get("authorization_scope")
    if authorization.get("paid_run_authorized") is not True:
        raise ValueError("paid matrix execution is not authorized")
    if not expected_scope or authorization.get("authorization_scope") != expected_scope:
        raise ValueError("authorization scope does not match execution.authorization_scope")
    if not authorization.get("authorized_by") or not authorization.get("authorized_at"):
        raise ValueError("authorization identity and timestamp are required")
    if not authorization.get("run_id"):
        raise ValueError("authorization must name one unique run_id")


def select_cells(root: Path, cells: list[CellSpec], keys: list[str]) -> list[CellSpec]:
    selected = cells
    if keys:
        requested = set(keys)
        selected = [cell for cell in cells if cell.key in requested]
        missing = sorted(requested - {cell.key for cell in selected})
        if missing:
            raise ValueError("unknown cell key(s): " + ", ".join(missing))
    for cell in selected:
        if cell_state(root, cell) == "ambiguous":
            raise ValueError(f"ambiguous cell requires classification: {cell.key}")
    return selected


def plan(manifest_path: Path) -> int:
    manifest = load_json(manifest_path)
    validate_official_manifest(manifest, manifest_path.parent)
    validate_backups(manifest)
    cells = build_cells(manifest)
    states = Counter(cell_state(manifest_path.parent, cell) for cell in cells)
    backups = {
        str(model["slug"]): model.get("backups", [])
        for model in manifest["models"]
        if model.get("backups")
    }
    print(
        json.dumps(
            {
                "cells": len(cells),
                "providers": sorted({cell.provider for cell in cells}),
                "provider_variants": sorted(
                    {f"{cell.provider}:{cell.provider_variant}" for cell in cells}
                ),
                "cell_states": dict(sorted(states.items())),
                "backups": backups,
                "authorization": manifest.get("authorization"),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("plan")
    subparsers.add_parser("report")
    run = subparsers.add_parser("run")
    run.add_argument("--stage-id", required=True)
    run.add_argument("--provider-cap", type=int, required=True)
    run.add_argument("--model-cap", type=int, required=True)
    run.add_argument("--evaluation-cap", type=int, required=True)
    run.add_argument("--cell", action="append", default=[])
    args = parser.parse_args()
    manifest_path = args.manifest.resolve()
    try:
        if args.command == "plan":
            return plan(manifest_path)
        manifest = load_json(manifest_path)
        validate_official_manifest(manifest, manifest_path.parent)
        validate_backups(manifest)
        if args.command == "report":
            from matrix_report import write_report

            with coordinator_lock(manifest_path.parent, manifest):
                write_report(manifest, manifest_path.parent)
            return 0
        ensure_authorized(manifest)
        worktree_preflight(manifest)
        coordinator = RollingCoordinator(
            manifest_path,
            provider_cap=args.provider_cap,
            model_cap=args.model_cap,
            evaluation_cap=args.evaluation_cap,
        )
        cells = select_cells(coordinator.root, coordinator.cells, args.cell)
        with coordinator_lock(coordinator.root, manifest):
            result = asyncio.run(coordinator.run_stage(args.stage_id, cells))
        return 20 if result.failures else 0
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"agent matrix stopped: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
