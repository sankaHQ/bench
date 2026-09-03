#!/usr/bin/env python3
"""Generate and evaluate one immutable pass@1 matrix cell.

`scripts/run_agent_matrix.py` schedules cells and calls this driver once per phase
through the manifest's ``execution.cell_command`` template. Generation and evaluation
are separate phases so the coordinator can release scarce provider slots while bounding
local evaluator processes. A generation failure is terminal evidence; a generated
candidate may be evaluated later but is never regenerated or overwritten. Every cell
writes the marker lines the coordinator reads back (``GENERATION_DONE``,
``DRIVER_DONE``) so a resumed run can tell terminal cells from ambiguous ones.

Phases:

- ``prepare``  — once per run: trusted marketplace snapshot in the run's SANKA_HOME,
  the pinned Sanka CLI and extension versions, and a toolchain record.
- ``generate`` — run the agent harness for the cell into ``candidates/``.
- ``evaluate`` — grade the frozen candidate with the tool-neutral evaluator into
  ``reports/``.
- ``full``     — generate then evaluate (single-process runs and tests).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ALLOWED_KEYS = {
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "OPENAI_API_KEY",
    "FIREWORKS_API_KEY",
    "DEEPINFRA_API_KEY",
    "TOGETHER_API_KEY",
}
OFFICIAL_MARKETPLACE = "https://github.com/sankaHQ/extensions.git"
DRF_EXTENSION_ID = "sanka/drf-to-fastapi"
DRF_EXTENSION_DISTRIBUTION = "sanka-extension-drf-to-fastapi"


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def read_allowlisted_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw or raw.lstrip().startswith("#") or "=" not in raw:
            continue
        name, value = raw.split("=", 1)
        name = name.strip()
        if name not in ALLOWED_KEYS:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[name] = value
    return values


def append_line(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line.rstrip("\n") + "\n")


def contains_marker(path: Path, prefix: str) -> bool:
    if not path.is_file():
        return False
    return any(line.startswith(prefix) for line in path.read_text(encoding="utf-8").splitlines())


@dataclass(frozen=True)
class Cell:
    task_id: str
    task_suffix: str
    model_slug: str
    model_id: str
    candidate_slug: str
    agent: str
    provider: str
    provider_variant: str
    actual_model_id: str
    route_kind: str
    billing_mode: str
    gateway_profile: str | None
    config: str
    sample: int
    samples: int

    @property
    def candidate_id(self) -> str:
        """Matches ``run_agent_matrix.CellSpec.candidate_id`` exactly."""
        base = f"{self.task_id}-{self.candidate_slug}-{self.config}"
        return f"{base}-s{self.sample}" if self.samples > 1 else base

    @property
    def with_sanka(self) -> bool:
        return self.config.startswith("with-sanka")


@dataclass(frozen=True)
class Paths:
    root: Path
    worktree: Path
    candidate: Path
    report: Path
    log: Path
    sandbox: Path
    claude_config: Path
    sanka_home: Path


def resolve_cell(
    manifest: dict[str, Any], task: str, model_slug: str, config: str, sample: int
) -> Cell:
    tasks = [str(item) for item in manifest["suite"]["tasks"]]
    task_id = task if task in tasks else next((t for t in tasks if t.endswith(f"-{task}")), "")
    if task_id not in tasks:
        raise ValueError(f"task not present in manifest: {task}")
    if config not in manifest["execution"]["configurations"]:
        raise ValueError(f"configuration not present in manifest: {config}")
    samples = int(manifest["execution"].get("samples", 1))
    if not 1 <= sample <= samples:
        raise ValueError(f"sample must be 1..{samples}, got {sample}")
    matches = [model for model in manifest["models"] if model["slug"] == model_slug]
    if len(matches) != 1:
        raise ValueError(f"model slug must match exactly once: {model_slug}")
    model = matches[0]
    return Cell(
        task_id=task_id,
        task_suffix=task_id.rsplit("-", 1)[-1],
        model_slug=model_slug,
        model_id=str(model.get("requested_model_id") or model.get("model_id") or ""),
        candidate_slug=str(model["candidate_slug"]),
        agent=str(model.get("harness") or model.get("agent") or ""),
        provider=str(model["provider"]),
        provider_variant=str(model.get("provider_variant") or "standard"),
        actual_model_id=str(
            model.get("actual_model_id")
            or model.get("requested_model_id")
            or model.get("model_id")
            or ""
        ),
        route_kind=str(model.get("route_kind") or "legacy"),
        billing_mode=str(model.get("billing_mode") or "unknown"),
        gateway_profile=(
            str(model["gateway_profile"]) if model.get("gateway_profile") is not None else None
        ),
        config=config,
        sample=sample,
        samples=samples,
    )


def resolve_paths(manifest_path: Path, manifest: dict[str, Any], cell: Cell) -> Paths:
    root = manifest_path.parent.resolve()
    worktree_raw = str(manifest["toolchain"]["worktree"])
    if not worktree_raw or worktree_raw.startswith("PENDING_"):
        raise ValueError("manifest worktree is not armed")
    sandbox = root / "sandboxes" / cell.candidate_id
    return Paths(
        root=root,
        worktree=Path(worktree_raw).resolve(),
        candidate=root / "candidates" / cell.task_id / cell.candidate_id,
        report=root / "reports" / f"{cell.task_id}-{cell.candidate_id}.json",
        log=root / "logs" / f"run-{cell.task_suffix}-{cell.candidate_id}.log",
        sandbox=sandbox,
        claude_config=sandbox / "claude-config",
        sanka_home=sandbox / "sanka-home",
    )


def route_environment(base: dict[str, str], cell: Cell) -> dict[str, str]:
    env = dict(base)
    if cell.route_kind == "anthropic-native":
        for name in ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY"):
            env.pop(name, None)
        return env
    if cell.route_kind == "gateway":
        auth = [name for name in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY") if env.get(name)]
        if not env.get("ANTHROPIC_BASE_URL"):
            raise ValueError("gateway route requires a base URL")
        if len(auth) != 1:
            raise ValueError("gateway route requires exactly one credential")
    return env


def _armed_path(manifest: dict[str, Any], key: str) -> Path:
    raw = str(manifest["toolchain"].get(key, ""))
    if not raw or raw in {"VERIFY_AT_LAUNCH"} or raw.startswith("PENDING_"):
        raise ValueError(f"manifest toolchain.{key} is not armed")
    return Path(raw).resolve()


def validate_prerequisites(manifest: dict[str, Any], cell: Cell, paths: Paths) -> dict[str, Path]:
    expected_sha = str(manifest["benchmark_sha"])
    if not re.fullmatch(r"[0-9a-f]{40}", expected_sha):
        raise ValueError("manifest benchmark SHA is not armed")
    actual_sha = subprocess.check_output(
        ["git", "-C", str(paths.worktree), "rev-parse", "HEAD"], text=True
    ).strip()
    if actual_sha != expected_sha:
        raise ValueError(f"worktree SHA mismatch: expected {expected_sha}, got {actual_sha}")
    task = paths.worktree / "tasks" / "drf-fastapi" / cell.task_id
    python = paths.worktree / ".venv" / "bin" / "python"
    bench = paths.worktree / ".venv" / "bin" / "sanka-bench"
    agent_runner = paths.worktree / "scripts" / "run_agent_candidate.py"
    tools: dict[str, Path] = {
        "task": task,
        "python": python,
        "bench": bench,
        "agent_runner": agent_runner,
    }
    needs_env = not (cell.route_kind == "anthropic-native" and cell.billing_mode == "subscription")
    if needs_env:
        tools["env"] = _armed_path(manifest, "env_path")
    agent_tool = "claude" if cell.agent == "claude-code" else "codex"
    tools[agent_tool] = _armed_path(manifest, f"{agent_tool}_bin")
    if cell.with_sanka:
        tools["sanka"] = _armed_path(manifest, "sanka_bin")
    required = [task / "source", task / "public-tests" / "scenarios.json", python, bench]
    required.append(tools[agent_tool])
    required.append(agent_runner)
    if needs_env:
        required.append(tools["env"])
    if cell.with_sanka:
        required.append(tools["sanka"])
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise ValueError("missing prerequisite(s): " + ", ".join(missing))
    expected_digest = str(manifest["toolchain"].get("agent_runner_sha256", ""))
    actual_digest = hashlib.sha256(agent_runner.read_bytes()).hexdigest()
    if actual_digest != expected_digest:
        raise ValueError(
            f"agent runner digest mismatch: expected {expected_digest}, got {actual_digest}"
        )
    return tools


def sanka_versions(sanka_bin: Path) -> tuple[str, str]:
    """(`sanka --version`, installed DRF extension version) for the pinned runtime env."""
    version = subprocess.run(
        [str(sanka_bin), "--version"], capture_output=True, text=True, check=False
    ).stdout.strip()
    python = sanka_bin.parent / "python"
    probe = subprocess.run(
        [
            str(python),
            "-c",
            f"import importlib.metadata as m; print(m.version({DRF_EXTENSION_DISTRIBUTION!r}))",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return version, probe.stdout.strip() if probe.returncode == 0 else ""


def check_sanka_toolchain(manifest: dict[str, Any], sanka_bin: Path) -> dict[str, str]:
    """The run measures exactly the Sanka the manifest names; anything else aborts."""
    version, extension = sanka_versions(sanka_bin)
    expected_cli = str(manifest["toolchain"].get("sanka_cli", ""))
    expected_extension = str(manifest["toolchain"].get("extension_version", ""))
    if not expected_cli or version != expected_cli:
        raise ValueError(f"sanka CLI mismatch: expected {expected_cli!r}, got {version!r}")
    if not expected_extension or extension != expected_extension:
        raise ValueError(
            f"{DRF_EXTENSION_DISTRIBUTION} mismatch: expected {expected_extension!r}, "
            f"installed {extension!r} (uv sync removes ad-hoc wheels; reinstall the "
            "release wheels into the runtime environment)"
        )
    return {"sanka_cli": version, "extension_version": extension}


def prepare_sanka_home(manifest: dict[str, Any], paths: Paths, sanka_bin: Path) -> dict[str, Any]:
    """Trusted marketplace snapshot for the run; recorded so every cell shares one."""
    paths.sanka_home.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["SANKA_HOME"] = str(paths.sanka_home)
    added = subprocess.run(
        [str(sanka_bin), "extension", "marketplace", "add", OFFICIAL_MARKETPLACE, "--json"],
        cwd=paths.root,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    if added.returncode != 0 and "SANKA_MARKETPLACE_EXISTS" not in added.stdout:
        raise ValueError(f"marketplace add failed: {added.stdout[:800]}{added.stderr[:400]}")
    listed = subprocess.run(
        [str(sanka_bin), "extension", "marketplace", "list", "--json"],
        cwd=paths.root,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        records = json.loads(listed.stdout).get("data", {}).get("records", [])
    except (json.JSONDecodeError, AttributeError):
        records = []
    snapshot = next(
        (
            record.get("snapshot_digest")
            for record in records
            if isinstance(record, dict) and OFFICIAL_MARKETPLACE.rstrip(".git") in str(record)
        ),
        None,
    )
    record = {
        "prepared_at": utc_now(),
        "sanka_home": str(paths.sanka_home),
        "marketplace": OFFICIAL_MARKETPLACE,
        "snapshot_digest": snapshot,
        **check_sanka_toolchain(manifest, sanka_bin),
    }
    (paths.root / "toolchain-check.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return record


def ensure_generation_authorized(manifest: dict[str, Any]) -> None:
    authorization = manifest.get("authorization", {})
    if authorization.get("paid_run_authorized") is not True:
        raise ValueError("paid generation is not authorized in the manifest")
    expected_scope = manifest["execution"].get("authorization_scope")
    if not expected_scope or authorization.get("authorization_scope") != expected_scope:
        raise ValueError(f"authorization scope must be exactly {expected_scope!r}")
    run_id = authorization.get("run_id")
    if not run_id or os.environ.get("SANKA_BENCH_COORDINATOR_RUN_ID") != run_id:
        raise ValueError("generation must be owned by the authorized foreground coordinator")


def retry_metadata(manifest: dict[str, Any], cell: Cell, root: Path) -> tuple[int, str | None]:
    retries = manifest["execution"].get("infrastructure_retries", {})
    metadata = retries.get(cell.candidate_id)
    if metadata is None:
        return 1, None
    attempt = int(metadata.get("attempt", 0))
    prior_failure = str(metadata.get("prior_failure") or "")
    ledger = str(metadata.get("authorization_ledger") or "")
    if attempt != 2 or not prior_failure or not ledger:
        raise ValueError(f"invalid infrastructure retry authorization for {cell.candidate_id}")
    if not (root / ledger).is_file():
        raise ValueError(f"infrastructure retry ledger is missing: {ledger}")
    return attempt, prior_failure


def generation_command(
    manifest: dict[str, Any],
    cell: Cell,
    paths: Paths,
    tools: dict[str, Path],
    *,
    attempt: int,
    prior_failure: str | None,
) -> list[str]:
    command = [
        str(tools["python"]),
        str(tools["agent_runner"]),
        "--task",
        str(Path("tasks") / "drf-fastapi" / cell.task_id),
        "--candidate-id",
        cell.candidate_id,
        "--agent",
        cell.agent,
        "--agent-bin",
        str(tools["claude"] if cell.agent == "claude-code" else tools["codex"]),
        "--out",
        str(paths.candidate),
        "--sandbox",
        str(paths.sandbox),
        "--model",
        cell.model_id,
        "--actual-model-id",
        cell.actual_model_id,
        "--route-kind",
        cell.route_kind,
        "--billing-mode",
        cell.billing_mode,
        "--max-turns",
        str(int(manifest["execution"]["max_turns"])),
        "--provider-variant",
        cell.provider_variant,
    ]
    if cell.gateway_profile is not None:
        command.extend(["--gateway-profile", cell.gateway_profile])
    if cell.agent == "codex":
        command.extend(["--provider", cell.provider])
    if attempt > 1:
        assert prior_failure is not None
        command.extend(["--attempt", str(attempt), "--prior-failure", prior_failure])
    if cell.with_sanka:
        command.extend(["--sanka-bin", str(tools["sanka"])])
    return command


def normalize_candidate_metadata(paths: Paths, cell: Cell) -> bool:
    """Keep provider_variant out of candidate.yaml provenance (schema v0.2).

    GENERATED.md keeps the disclosure.
    """
    candidate_yaml = paths.candidate / "candidate.yaml"
    disclosure = paths.candidate / "GENERATED.md"
    if not candidate_yaml.is_file() or not disclosure.is_file():
        raise ValueError("generated candidate metadata is incomplete")
    expected_line = f"  provider_variant: {cell.provider_variant}\n"
    text = candidate_yaml.read_text(encoding="utf-8")
    if expected_line not in text:
        return False
    if text.count(expected_line) != 1:
        raise ValueError("candidate metadata has ambiguous provider_variant lines")
    if f"| Provider variant | {cell.provider_variant} |" not in disclosure.read_text(
        encoding="utf-8"
    ):
        raise ValueError("provider variant disclosure is missing from GENERATED.md")
    candidate_yaml.write_text(text.replace(expected_line, ""), encoding="utf-8")
    return True


def run_generation(
    manifest: dict[str, Any], cell: Cell, paths: Paths, tools: dict[str, Path]
) -> int:
    if paths.candidate.exists() or paths.report.exists() or paths.log.exists():
        raise ValueError(f"pass@1 artifact already exists for {cell.candidate_id}")
    for directory in (paths.candidate.parent, paths.report.parent, paths.log.parent):
        directory.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    if "env" in tools:
        environment.update(read_allowlisted_env(tools["env"]))
    environment = route_environment(environment, cell)
    required_key = (
        {"openai": "OPENAI_API_KEY", "fireworks": "FIREWORKS_API_KEY"}.get(cell.provider)
        if cell.agent == "codex"
        else None
    )
    if required_key and not environment.get(required_key):
        raise ValueError(f"required provider credential is unavailable: {required_key}")
    toolchain: dict[str, str] = {}
    if cell.with_sanka:
        if not (paths.root / "toolchain-check.json").is_file():
            raise ValueError("run the prepare phase before with-sanka cells")
        prepared_sanka_home = paths.root / "sanka-home"
        if not prepared_sanka_home.is_dir():
            raise ValueError("prepared Sanka home is missing")
        paths.sandbox.mkdir(parents=True, exist_ok=True)
        shutil.copytree(prepared_sanka_home, paths.sanka_home)
        environment["SANKA_HOME"] = str(paths.sanka_home)
        toolchain = check_sanka_toolchain(manifest, tools["sanka"])
    attempt, prior_failure = retry_metadata(manifest, cell, paths.root)
    header = [
        f"RUN_START_UTC={utc_now()}",
        f"BENCH_SHA={manifest['benchmark_sha']}",
        f"TASK_ID={cell.task_id}",
        f"CANDIDATE_ID={cell.candidate_id}",
        f"SAMPLE={cell.sample}/{cell.samples}",
        f"AGENT={cell.agent}",
        f"PROVIDER={cell.provider}",
        f"PROVIDER_VARIANT={cell.provider_variant}",
        f"MODEL_ID={cell.model_id}",
        f"CONFIG={cell.config}",
        f"ATTEMPT={attempt}",
        f"SANKA_CLI={toolchain.get('sanka_cli', 'not offered')}",
        f"SANKA_EXTENSION={toolchain.get('extension_version', 'not offered')}",
        f"WAVE_ID={os.environ.get('SANKA_BENCH_WAVE_ID', 'rolling-unset')}",
    ]
    paths.log.write_text("\n".join(header) + "\n", encoding="utf-8")
    started = time.monotonic()
    with paths.log.open("a", encoding="utf-8") as handle:
        outcome = subprocess.run(
            generation_command(
                manifest, cell, paths, tools, attempt=attempt, prior_failure=prior_failure
            ),
            cwd=paths.worktree,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
            check=False,
        )
    if outcome.returncode == 0 and normalize_candidate_metadata(paths, cell):
        append_line(
            paths.log,
            "METADATA_NORMALIZED provider_variant_from_candidate_yaml=removed "
            "disclosure_preserved=GENERATED.md overlay_unchanged=true",
        )
    wall = round(time.monotonic() - started)
    append_line(paths.log, f"GENERATION_END_UTC={utc_now()}")
    append_line(paths.log, f"GENERATION_DONE run_exit={outcome.returncode} wall_seconds={wall}")
    if outcome.returncode != 0:
        append_line(
            paths.log,
            f"DRIVER_DONE task={cell.task_id} cid={cell.candidate_id} "
            f"run_exit={outcome.returncode} eval_exit=skipped wall_seconds={wall}",
        )
        return 20
    return 0


def run_evaluation(cell: Cell, paths: Paths, tools: dict[str, Path]) -> int:
    if not contains_marker(paths.log, "GENERATION_DONE run_exit=0 "):
        raise ValueError(f"successful generation marker missing for {cell.candidate_id}")
    if contains_marker(paths.log, "DRIVER_DONE "):
        raise ValueError(f"terminal pass@1 cell already exists for {cell.candidate_id}")
    if not paths.candidate.is_dir():
        raise ValueError(f"generated candidate is missing for {cell.candidate_id}")
    if paths.report.exists():
        raise ValueError(
            f"evaluation report already exists without terminal marker: {paths.report}"
        )
    append_line(paths.log, f"EVAL_START_UTC={utc_now()}")
    started = time.monotonic()
    with paths.log.open("a", encoding="utf-8") as handle:
        outcome = subprocess.run(
            [
                str(tools["bench"]),
                "evaluate",
                "--runner",
                "local",
                "--task",
                str(Path("tasks") / "drf-fastapi" / cell.task_id),
                "--candidate",
                str(paths.candidate),
                "--output",
                str(paths.report),
            ],
            cwd=paths.worktree,
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
            check=False,
        )
    wall = round(time.monotonic() - started)
    append_line(paths.log, f"EVAL_END_UTC={utc_now()}")
    append_line(paths.log, f"EVAL_DONE eval_exit={outcome.returncode} wall_seconds={wall}")
    recorded = "recorded" if paths.report.is_file() else "unknown"
    append_line(
        paths.log,
        f"DRIVER_DONE task={cell.task_id} cid={cell.candidate_id} "
        f"run_exit=0 eval_exit={outcome.returncode} wall_seconds={recorded}",
    )
    return 0 if paths.report.is_file() else 21


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("prepare", "generate", "evaluate", "full"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--task")
    parser.add_argument("--model")
    parser.add_argument("--config")
    parser.add_argument("--sample", type=int, default=1)
    args = parser.parse_args()
    manifest_path = args.manifest.resolve()
    try:
        manifest = load_json(manifest_path)
        if args.phase == "prepare":
            root = manifest_path.parent.resolve()
            paths = Paths(
                root=root,
                worktree=_armed_path(manifest, "worktree"),
                candidate=root,
                report=root,
                log=root,
                sandbox=root,
                claude_config=root / "claude-config",
                sanka_home=root / "sanka-home",
            )
            record = prepare_sanka_home(manifest, paths, _armed_path(manifest, "sanka_bin"))
            print(json.dumps(record, indent=2, sort_keys=True))
            return 0
        if not (args.task and args.model and args.config):
            parser.error("--task, --model, and --config are required for cell phases")
        cell = resolve_cell(manifest, args.task, args.model, args.config, args.sample)
        paths = resolve_paths(manifest_path, manifest, cell)
        tools = validate_prerequisites(manifest, cell, paths)
        if args.phase in {"generate", "full"}:
            ensure_generation_authorized(manifest)
            outcome = run_generation(manifest, cell, paths, tools)
            if outcome != 0:
                return outcome
        if args.phase in {"evaluate", "full"}:
            return run_evaluation(cell, paths, tools)
        return 0
    except (OSError, TypeError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(f"cell driver error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
