from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from run_agent_matrix import (  # noqa: E402
    RollingCoordinator,
    artifacts,
    build_cells,
    cell_state,
    ensure_authorized,
    prioritized,
    validate_backups,
    worktree_preflight,
)


def manifest() -> dict[str, Any]:
    return {
        "schema": "sanka-bench/model-matrix-run-manifest/v1",
        "benchmark_sha": "0" * 40,
        "suite": {
            "tasks": ["drf-fastapi-001"],
            "route_weights": {"drf-fastapi-001": 14},
        },
        "execution": {
            "configurations": ["alone"],
            "expected_rows": 3,
            "authorization_scope": "test-three-cell-run",
            "cell_command": [
                "{python}",
                "driver.py",
                "{phase}",
                "--manifest",
                "{manifest}",
                "--task",
                "{task_suffix}",
                "--model",
                "{model}",
                "--config",
                "{config}",
            ],
        },
        "models": [
            {
                "slug": "a-fail",
                "candidate_slug": "codex-a-fail",
                "provider": "fireworks",
                "provider_variant": "serverless-standard",
                "model_id": "accounts/fireworks/models/a",
            },
            {
                "slug": "m-generated",
                "candidate_slug": "codex-m-generated",
                "provider": "openai",
                "provider_variant": "api-standard",
                "model_id": "m-generated",
            },
            {
                "slug": "z-queued",
                "candidate_slug": "codex-z-queued",
                "provider": "fireworks",
                "provider_variant": "serverless-standard",
                "model_id": "accounts/fireworks/models/z",
                "backups": [
                    {
                        "label": "Fireworks on-demand Fast",
                        "provider": "fireworks",
                        "provider_variant": "on-demand-fast",
                        "model_id": "accounts/example/deployments/z-fast",
                        "wire_api": "responses",
                        "adapter": "codex-cli-0.150",
                        "status": "unqualified",
                    },
                    {
                        "label": "DeepInfra qualification cohort",
                        "provider": "deepinfra",
                        "provider_variant": "priority-chat",
                        "model_id": "example/z",
                        "wire_api": "chat-completions",
                        "adapter": "pending-chat-adapter",
                        "status": "unqualified",
                    },
                ],
            },
        ],
        "authorization": {
            "paid_run_authorized": True,
            "authorization_scope": "test-three-cell-run",
            "authorized_by": "test-human",
            "authorized_at": "2026-09-01T00:00:00Z",
            "run_id": "test-run-1",
        },
    }


class FakeCoordinator(RollingCoordinator):
    def __init__(self, *args: Any, fail_key: str, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fail_key = fail_key
        self.generation_starts: list[str] = []
        self.evaluation_starts: list[str] = []

    def aggregate(self, stage_id: str) -> int:
        return 0

    async def _process(self, cell, phase: str, stage_id: str) -> int:  # type: ignore[override]
        paths = artifacts(self.root, cell)
        if phase == "generate":
            self.generation_starts.append(cell.key)
            await asyncio.sleep(0.005)
            paths.log.parent.mkdir(parents=True, exist_ok=True)
            if cell.key == self.fail_key:
                paths.log.write_text(
                    "GENERATION_DONE run_exit=1 wall_seconds=1\n"
                    "DRIVER_DONE run_exit=1 eval_exit=skipped\n",
                    encoding="utf-8",
                )
                return 20
            paths.candidate.mkdir(parents=True)
            paths.log.write_text("GENERATION_DONE run_exit=0 wall_seconds=1\n", encoding="utf-8")
            return 0
        self.evaluation_starts.append(cell.key)
        await asyncio.sleep(0.02)
        paths.report.parent.mkdir(parents=True, exist_ok=True)
        paths.report.write_text('{"status":"passed"}\n', encoding="utf-8")
        with paths.log.open("a", encoding="utf-8") as handle:
            handle.write("DRIVER_DONE run_exit=0 eval_exit=0\n")
        return 0


def write_manifest(root: Path, value: dict[str, Any] | None = None) -> Path:
    path = root / "run-manifest.json"
    path.write_text(json.dumps(value or manifest(), indent=2) + "\n", encoding="utf-8")
    return path


def test_manifest_preserves_provider_variants_and_declared_backups() -> None:
    value = manifest()
    validate_backups(value)
    cells = build_cells(value)
    assert len(cells) == 3
    assert {cell.provider_variant for cell in cells} == {
        "api-standard",
        "serverless-standard",
    }
    backup = value["models"][2]["backups"][0]
    assert backup["provider_variant"] == "on-demand-fast"
    assert backup["status"] == "unqualified"


def test_qualified_backup_requires_evidence() -> None:
    value = manifest()
    value["models"][2]["backups"][0]["status"] = "qualified"
    with pytest.raises(ValueError, match="qualification_evidence"):
        validate_backups(value)
    value["models"][2]["backups"][0]["qualification_evidence"] = {"probe_digest": "sha256:abc"}
    validate_backups(value)


def test_paid_execution_requires_exact_manifest_scope() -> None:
    value = manifest()
    ensure_authorized(value)
    value["authorization"]["authorization_scope"] = "different-run"
    with pytest.raises(ValueError, match="scope"):
        ensure_authorized(value)


def test_worktree_preflight_pins_clean_exact_sha(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Bench Test"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "bench@example.invalid"],
        check=True,
    )
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("clean\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "tracked.txt"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "fixture"], check=True)
    sha = subprocess.check_output(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True
    ).strip()
    value = {"benchmark_sha": sha, "toolchain": {"worktree": str(tmp_path)}}
    assert worktree_preflight(value)["benchmark_sha"] == sha
    tracked.write_text("dirty\n", encoding="utf-8")
    with pytest.raises(ValueError, match="tracked changes"):
        worktree_preflight(value)


def test_generated_candidates_are_prioritized_and_never_regenerated() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        cells = build_cells(manifest())
        generated = next(cell for cell in cells if cell.model_slug == "m-generated")
        paths = artifacts(root, generated)
        paths.candidate.mkdir(parents=True)
        paths.log.parent.mkdir(parents=True)
        paths.log.write_text("GENERATION_DONE run_exit=0 wall_seconds=1\n", encoding="utf-8")
        assert cell_state(root, generated) == "generated"
        assert prioritized(root, cells)[0] == generated


def test_terminal_marker_requires_consistent_artifacts() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        cell = build_cells(manifest())[0]
        paths = artifacts(root, cell)
        paths.log.parent.mkdir(parents=True)
        paths.log.write_text("DRIVER_DONE run_exit=0 eval_exit=0\n", encoding="utf-8")
        assert cell_state(root, cell) == "ambiguous"


def test_generation_failure_stops_new_calls_but_drains_frozen_candidates() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        path = write_manifest(root)
        cells = build_cells(manifest())
        failed = next(cell for cell in cells if cell.model_slug == "a-fail")
        generated = next(cell for cell in cells if cell.model_slug == "m-generated")
        queued = next(cell for cell in cells if cell.model_slug == "z-queued")

        generated_paths = artifacts(root, generated)
        generated_paths.candidate.mkdir(parents=True)
        generated_paths.log.parent.mkdir(parents=True)
        generated_paths.log.write_text(
            "GENERATION_DONE run_exit=0 wall_seconds=1\n", encoding="utf-8"
        )

        coordinator = FakeCoordinator(
            path,
            provider_cap=1,
            model_cap=1,
            evaluation_cap=1,
            fail_key=failed.key,
        )
        result = asyncio.run(coordinator.run_stage("test-drain", cells))

        assert result.generation_failures == 1
        assert result.evaluation_failures == 0
        assert result.completed == 1
        assert result.drained_evaluations == 1
        assert result.stopped_before_generation == 1
        assert generated.key in coordinator.evaluation_starts
        assert generated.key not in coordinator.generation_starts
        assert queued.key not in coordinator.generation_starts
        assert cell_state(root, generated) == "terminal"
        assert cell_state(root, failed) == "terminal"
        assert cell_state(root, queued) == "untouched"


def test_cancelled_worker_is_terminated_before_control_returns() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        value = manifest()
        value["execution"]["cell_command"] = [
            "{python}",
            "-c",
            "import time; time.sleep(60)",
        ]
        path = write_manifest(root, value)
        coordinator = RollingCoordinator(path, provider_cap=1, model_cap=1, evaluation_cap=1)
        cell = coordinator.cells[0]

        async def cancel_worker() -> None:
            worker = asyncio.create_task(coordinator._process(cell, "generate", "cancel"))
            for _ in range(100):
                if coordinator.processes:
                    break
                await asyncio.sleep(0.001)
            assert coordinator.processes
            process = next(iter(coordinator.processes))
            worker.cancel()
            with pytest.raises(asyncio.CancelledError):
                await worker
            assert process.returncode is not None
            assert not coordinator.processes

        asyncio.run(cancel_worker())
