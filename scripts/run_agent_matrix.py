#!/usr/bin/env python3
"""Run a durable pass@1 agent matrix under one foreground coordinator.

The manifest owns cell identity, exact provider variant, commands, and paid-run
authorization. Workers own only cell artifacts. The coordinator is the single
aggregate writer and never retries or silently substitutes a provider.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import signal
import subprocess
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


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


@dataclass(frozen=True)
class CellSpec:
    task: str
    task_suffix: str
    model_slug: str
    candidate_slug: str
    provider: str
    provider_variant: str
    config: str
    route_weight: int

    @property
    def candidate_id(self) -> str:
        return f"{self.task}-{self.candidate_slug}-{self.config}"

    @property
    def key(self) -> str:
        return f"{self.task}:{self.model_slug}:{self.config}"


@dataclass(frozen=True)
class CellArtifacts:
    candidate: Path
    report: Path
    log: Path


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
            "max_generation_total": self.max_generation_total,
            "max_evaluations": self.max_evaluations,
            "max_generation_by_provider": dict(self.max_generation_by_provider or {}),
            "max_generation_by_model": dict(self.max_generation_by_model or {}),
            "elapsed_seconds": round(self.elapsed_seconds, 3),
        }


def build_cells(manifest: dict[str, Any]) -> list[CellSpec]:
    cells: list[CellSpec] = []
    weights = manifest["suite"]["route_weights"]
    configurations = manifest["execution"]["configurations"]
    for task in manifest["suite"]["tasks"]:
        suffix = str(task).rsplit("-", 1)[-1]
        for model in manifest["models"]:
            variant = str(model.get("provider_variant") or "standard")
            for config in configurations:
                cells.append(
                    CellSpec(
                        task=str(task),
                        task_suffix=suffix,
                        model_slug=str(model["slug"]),
                        candidate_slug=str(model["candidate_slug"]),
                        provider=str(model["provider"]),
                        provider_variant=variant,
                        config=str(config),
                        route_weight=int(weights[task]),
                    )
                )
    expected = int(manifest["execution"]["expected_rows"])
    if len(cells) != expected:
        raise ValueError(f"manifest expands to {len(cells)} cells, expected {expected}")
    if len({cell.key for cell in cells}) != len(cells):
        raise ValueError("manifest expands to duplicate cell keys")
    return cells


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
        ["git", "-C", str(worktree), "rev-parse", "HEAD"], text=True
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
    )
    if status.returncode != 0 or status.stdout.strip():
        raise ValueError("benchmark worktree has tracked changes")
    return {"worktree": str(worktree), "benchmark_sha": actual}


def artifacts(root: Path, cell: CellSpec) -> CellArtifacts:
    return CellArtifacts(
        candidate=root / "candidates" / cell.task / cell.candidate_id,
        report=root / "reports" / f"{cell.task}-{cell.candidate_id}.json",
        log=root / "logs" / f"run-{cell.task_suffix}-{cell.candidate_id}.log",
    )


def marker_lines(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def cell_state(root: Path, cell: CellSpec) -> str:
    paths = artifacts(root, cell)
    lines = marker_lines(paths.log)
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
    if paths.log.exists() or paths.candidate.exists() or paths.report.exists():
        return "ambiguous"
    return "untouched"


def prioritized(root: Path, cells: Iterable[CellSpec]) -> list[CellSpec]:
    states = {cell.key: cell_state(root, cell) for cell in cells}
    return sorted(
        cells,
        key=lambda cell: (
            0 if states[cell.key] == "generated" else 1,
            -cell.route_weight,
            cell.provider,
            cell.model_slug,
            0 if cell.config == "alone" else 1,
            cell.task,
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
        validate_backups(self.manifest)
        self.cells = build_cells(self.manifest)
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
        environment = dict(os.environ)
        environment.update(
            {
                "SANKA_BENCH_WAVE_ID": stage_id,
                "SANKA_BENCH_WAVE_CONCURRENCY": str(self.stage_concurrency),
                "SANKA_BENCH_TIMING_METHODOLOGY": "rolling-provider-queue",
                "SANKA_BENCH_COORDINATOR_RUN_ID": str(self.manifest["authorization"]["run_id"]),
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
                await self.activity.generation_started(cell)
                self.event(
                    "generation-start",
                    stage_id=stage_id,
                    cell=cell.key,
                    provider_variant=cell.provider_variant,
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
                )
                if returncode != 0:
                    result.generation_failures += 1
                    self.stop_generation.set()
                    return

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
        if not template:
            return 0
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
            for cell in prioritized(self.root, cells)
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
        if self.aggregate(stage_id) != 0:
            result.evaluation_failures += 1
        atomic_json(self.root / "waves" / f"{stage_id}.json", result.as_dict())
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
        validate_backups(manifest)
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
