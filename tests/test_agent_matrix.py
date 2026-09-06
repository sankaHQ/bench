from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

from sanka_bench.hashing import digest_tree

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from run_agent_matrix import (  # noqa: E402
    RollingCoordinator,
    artifact_issues,
    artifacts,
    authorize_retry,
    build_cells,
    cell_input_digest,
    cell_state,
    ensure_authorized,
    prioritized,
    render_command,
    secret_hits,
    validate_backups,
    validate_official_manifest,
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


def official_manifest(root: Path) -> dict[str, Any]:
    transcript = b'{"type":"result","subtype":"success"}\n'
    qualification = {
        "schema": "sanka-bench/claude-route-qualification/v1",
        "status": "qualified",
        "requested_model_id": "claude-sonnet-5",
        "actual_model_id": "claude-sonnet-5-20260901",
        "provider": "anthropic",
        "provider_variant": "subscription-standard",
        "route_kind": "anthropic-native",
        "billing_mode": "subscription",
        "gateway_profile": None,
        "checks": {
            "tool_use": True,
            "streaming": True,
            "terminal_event": True,
            "usage_accounting": True,
        },
        "claude": {
            "version": "2.1.241",
            "sha256": "sha256:" + "1" * 64,
        },
        "evidence": {
            "prompt_sha256": "sha256:" + "2" * 64,
            "provider_sha256": "sha256:" + "3" * 64,
            "transcript_sha256": "sha256:" + hashlib.sha256(transcript).hexdigest(),
        },
    }
    path = root / "qualifications" / "sonnet.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(qualification, sort_keys=True) + "\n", encoding="utf-8")
    path.with_suffix(".jsonl").write_bytes(transcript)
    value = manifest()
    value["schema"] = "sanka-bench/model-matrix-run-manifest/v2"
    value["execution"]["configurations"] = ["alone", "with-sanka"]
    value["execution"]["expected_rows"] = 2
    value["execution"]["max_turns"] = 60
    value["execution"]["wall_clock_seconds"] = 3600
    value["execution"]["concurrency"] = {
        "provider_cap": 1,
        "model_cap": 1,
        "evaluation_cap": 1,
    }
    value["toolchain"] = {
        "claude_version": "2.1.241",
        "claude_bin_sha256": "sha256:" + "1" * 64,
        "sanka_skill_sha256": "sha256:" + "5" * 64,
    }
    value["models"] = [
        {
            "slug": "sonnet",
            "candidate_slug": "claude-code-sonnet",
            "harness": "claude-code",
            "provider": "anthropic",
            "provider_variant": "subscription-standard",
            "requested_model_id": "claude-sonnet-5",
            "actual_model_id": "claude-sonnet-5-20260901",
            "route_kind": "anthropic-native",
            "billing_mode": "subscription",
            "gateway_profile": None,
            "qualification": "qualifications/sonnet.json",
            "qualification_sha256": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    ]
    return value


def test_official_manifest_accepts_three_arm_ablation(tmp_path: Path) -> None:
    value = official_manifest(tmp_path)
    value["execution"]["configurations"] = ["alone", "sanka-cli", "with-sanka"]
    value["execution"]["expected_rows"] = 3
    value["execution"]["container_engine"] = "podman"

    validate_official_manifest(value, tmp_path)
    assert [cell.config for cell in build_cells(value)] == [
        "alone",
        "sanka-cli",
        "with-sanka",
    ]


def test_official_manifest_rejects_an_unknown_container_engine(tmp_path: Path) -> None:
    value = official_manifest(tmp_path)
    value["execution"]["container_engine"] = "magic"

    with pytest.raises(ValueError, match="container engine"):
        validate_official_manifest(value, tmp_path)


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


def test_manifest_rejects_unsafe_and_colliding_artifact_names() -> None:
    unsafe = manifest()
    unsafe["suite"]["tasks"] = ["../escape"]
    unsafe["suite"]["route_weights"] = {"../escape": 1}
    with pytest.raises(ValueError, match="unsafe task"):
        build_cells(unsafe)

    colliding = manifest()
    colliding["models"][1]["candidate_slug"] = colliding["models"][0]["candidate_slug"]
    with pytest.raises(ValueError, match="duplicate artifact"):
        build_cells(colliding)


def test_official_manifest_requires_claude_code_and_matching_qualification(
    tmp_path: Path,
) -> None:
    value = official_manifest(tmp_path)
    validate_official_manifest(value, tmp_path)

    value["models"][0]["harness"] = "codex"
    with pytest.raises(ValueError, match="Claude Code"):
        validate_official_manifest(value, tmp_path)


def test_official_manifest_rejects_changed_qualification_evidence(tmp_path: Path) -> None:
    value = official_manifest(tmp_path)
    qualification = tmp_path / value["models"][0]["qualification"]
    qualification.write_text('{"status":"changed"}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="qualification digest"):
        validate_official_manifest(value, tmp_path)


def test_official_manifest_rejects_route_and_identity_mismatch(tmp_path: Path) -> None:
    value = official_manifest(tmp_path)
    value["models"][0]["actual_model_id"] = "different-model"
    with pytest.raises(ValueError, match="actual model"):
        validate_official_manifest(value, tmp_path)


def test_official_manifest_requires_matching_harness_and_evidence_pins(tmp_path: Path) -> None:
    value = official_manifest(tmp_path)
    qualification = tmp_path / value["models"][0]["qualification"]
    evidence = json.loads(qualification.read_text(encoding="utf-8"))
    del evidence["claude"]
    qualification.write_text(json.dumps(evidence) + "\n", encoding="utf-8")
    value["models"][0]["qualification_sha256"] = (
        "sha256:" + hashlib.sha256(qualification.read_bytes()).hexdigest()
    )

    with pytest.raises(ValueError, match="Claude harness evidence"):
        validate_official_manifest(value, tmp_path)


def test_cell_input_digest_covers_model_prompts_toolchain_and_sample(tmp_path: Path) -> None:
    value = official_manifest(tmp_path)
    value["execution"].update(
        {
            "max_turns": 60,
            "wall_clock_seconds": 3600,
            "prompt_sha256": "sha256:" + "1" * 64,
            "sanka_prompt_sha256": "sha256:" + "2" * 64,
        }
    )
    value.setdefault("toolchain", {}).update(
        {
            "claude_version": "2.1.241",
            "claude_bin_sha256": "sha256:" + "3" * 64,
            "sanka_cli": "sanka, version 0.3.0",
            "sanka_skill_sha256": "sha256:" + "4" * 64,
        }
    )

    def digest(candidate: dict[str, Any], sample: int = 1) -> str:
        return cell_input_digest(
            candidate,
            task="drf-fastapi-001",
            model=candidate["models"][0],
            config="alone",
            sample=sample,
        )

    original = digest(value)
    assert original.startswith("sha256:")
    for section, key, replacement in (
        ("models", "requested_model_id", "different-model"),
        ("execution", "prompt_sha256", "sha256:" + "5" * 64),
        ("toolchain", "claude_version", "2.1.242"),
        ("toolchain", "sanka_skill_sha256", "sha256:" + "6" * 64),
    ):
        changed = copy.deepcopy(value)
        target = changed["models"][0] if section == "models" else changed[section]
        target[key] = replacement
        assert digest(changed) != original
    changed = copy.deepcopy(value)
    changed["execution"]["concurrency"]["model_cap"] = 2
    assert digest(changed) != original
    assert digest(value, sample=2) != original


def test_official_manifest_enforces_pinned_concurrency(tmp_path: Path) -> None:
    value = official_manifest(tmp_path)
    path = write_manifest(tmp_path, value)

    with pytest.raises(ValueError, match="pinned concurrency"):
        RollingCoordinator(path, provider_cap=2, model_cap=1, evaluation_cap=1)


def test_current_wave_is_persisted_before_report_aggregation(tmp_path: Path) -> None:
    path = write_manifest(tmp_path)
    coordinator = RollingCoordinator(path, provider_cap=1, model_cap=1, evaluation_cap=1)
    observed = False

    def aggregate(stage_id: str) -> int:
        nonlocal observed
        observed = (tmp_path / "waves" / f"{stage_id}.json").is_file()
        return 0

    coordinator.aggregate = aggregate  # type: ignore[method-assign]

    asyncio.run(coordinator.run_stage("current", []))

    assert observed


def test_official_manifest_requires_positive_budgets(tmp_path: Path) -> None:
    value = official_manifest(tmp_path)
    value["execution"]["wall_clock_seconds"] = 0

    with pytest.raises(ValueError, match="positive execution budgets"):
        validate_official_manifest(value, tmp_path)


def test_resume_refuses_missing_or_stale_input_digest(tmp_path: Path) -> None:
    cells = build_cells(official_manifest(tmp_path))
    cell = cells[0]
    paths = artifacts(tmp_path, cell)
    paths.candidate.mkdir(parents=True)
    paths.log.parent.mkdir(parents=True)
    paths.log.write_text("GENERATION_DONE run_exit=0 wall_seconds=1\n", encoding="utf-8")
    assert cell_state(tmp_path, cell) == "ambiguous"

    paths.log.write_text(
        f"INPUT_DIGEST=sha256:{'0' * 64}\nGENERATION_DONE run_exit=0 wall_seconds=1\n",
        encoding="utf-8",
    )
    assert cell_state(tmp_path, cell) == "ambiguous"

    paths.log.write_text(
        f"INPUT_DIGEST={cell.input_digest}\nGENERATION_DONE run_exit=0 wall_seconds=1\n",
        encoding="utf-8",
    )
    assert cell_state(tmp_path, cell) == "generated"

    sandbox_only = cells[1]
    artifacts(tmp_path, sandbox_only).sandbox.mkdir(parents=True)
    assert cell_state(tmp_path, sandbox_only) == "ambiguous"


def test_retry_preserves_the_failed_sandbox_with_the_incident(tmp_path: Path) -> None:
    value = manifest()
    manifest_path = write_manifest(tmp_path, value)
    cell = build_cells(value)[0]
    paths = artifacts(tmp_path, cell)
    paths.log.parent.mkdir(parents=True)
    paths.log.write_text("agent reported an error: at capacity\n", encoding="utf-8")
    paths.candidate.mkdir(parents=True)
    paths.sandbox.mkdir(parents=True)
    (paths.sandbox / "raw.jsonl").write_text("evidence\n", encoding="utf-8")

    ledger = authorize_retry(manifest_path, value, tmp_path, cell, "at capacity")

    attempt = ledger.parent / "attempt-1"
    assert (attempt / "sandbox" / "raw.jsonl").read_text() == "evidence\n"
    assert not paths.sandbox.exists()


def test_prioritized_alternates_the_first_lane_for_each_pair(tmp_path: Path) -> None:
    value = official_manifest(tmp_path)
    value["suite"] = {
        "tasks": ["drf-fastapi-001", "drf-fastapi-007"],
        "route_weights": {"drf-fastapi-001": 14, "drf-fastapi-007": 7},
    }
    value["execution"]["samples"] = 2
    value["execution"]["expected_rows"] = 8

    ordered = prioritized(tmp_path, build_cells(value))

    assert [(cell.task, cell.sample, cell.config) for cell in ordered] == [
        ("drf-fastapi-001", 1, "alone"),
        ("drf-fastapi-001", 1, "with-sanka"),
        ("drf-fastapi-001", 2, "with-sanka"),
        ("drf-fastapi-001", 2, "alone"),
        ("drf-fastapi-007", 1, "alone"),
        ("drf-fastapi-007", 1, "with-sanka"),
        ("drf-fastapi-007", 2, "with-sanka"),
        ("drf-fastapi-007", 2, "alone"),
    ]

    value = official_manifest(tmp_path)
    value["models"][0]["route_kind"] = "gateway"
    with pytest.raises(ValueError, match=r"gateway.*api_key"):
        validate_official_manifest(value, tmp_path)


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


def test_evaluation_worker_keeps_the_selected_container_engine_on_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    engine_dir = tmp_path / "homebrew" / "bin"
    engine_dir.mkdir(parents=True)
    engine = engine_dir / "podman"
    engine.write_text("#!/bin/sh\n", encoding="utf-8")
    engine.chmod(0o755)
    monkeypatch.setenv("PATH", f"{engine_dir}:/usr/bin:/bin")
    value = manifest()
    value["execution"]["container_engine"] = "podman"
    value["execution"]["cell_command"] = [
        "{python}",
        "-c",
        (
            "import os,sys; "
            "sys.exit(0 if os.environ['PATH'].split(os.pathsep)[0] == sys.argv[1] else 1)"
        ),
        str(engine_dir),
    ]
    path = write_manifest(tmp_path, value)
    coordinator = RollingCoordinator(path, provider_cap=1, model_cap=1, evaluation_cap=1)

    returncode = asyncio.run(coordinator._process(coordinator.cells[0], "evaluate", "path"))

    assert returncode == 0


def test_samples_multiply_cells_and_suffix_their_identities() -> None:
    data = manifest()
    data["execution"]["samples"] = 3
    data["execution"]["expected_rows"] = 9
    cells = build_cells(data)
    assert len(cells) == 9
    assert len({cell.key for cell in cells}) == 9
    ids = sorted(cell.candidate_id for cell in cells if cell.model_slug == "a-fail")
    assert ids == [
        "drf-fastapi-001-codex-a-fail-alone-s1",
        "drf-fastapi-001-codex-a-fail-alone-s2",
        "drf-fastapi-001-codex-a-fail-alone-s3",
    ]
    # single-sample manifests keep the historical identities byte for byte
    assert build_cells(manifest())[0].candidate_id == "drf-fastapi-001-codex-a-fail-alone"
    command = render_command(
        ["{python}", "--sample", "{sample}", "--id", "{candidate_id}"],
        Path("/m.json"),
        cells[1],
        "generate",
    )
    assert command[2] == "2" and command[4].endswith("-s2")
    data["execution"]["samples"] = 0
    with pytest.raises(ValueError):
        build_cells(data)


class FlakyCoordinator(FakeCoordinator):
    """Fails the first generation of ``fail_key`` like a provider capacity error."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.attempts: dict[str, int] = {}

    async def _process(self, cell, phase: str, stage_id: str) -> int:  # type: ignore[override]
        if phase == "generate" and cell.key == self.fail_key:
            self.attempts[cell.key] = self.attempts.get(cell.key, 0) + 1
            if self.attempts[cell.key] == 1:
                paths = artifacts(self.root, cell)
                paths.log.parent.mkdir(parents=True, exist_ok=True)
                paths.log.write_text(
                    "RUN_START_UTC=2026-09-03T00:00:00Z\n"
                    'agent reported an error: {"type": "turn.failed", "error": {"message": '
                    '"Selected model is at capacity. Please try a different model."}}\n'
                    "GENERATION_DONE run_exit=1 wall_seconds=18\n"
                    "DRIVER_DONE run_exit=1 eval_exit=skipped\n",
                    encoding="utf-8",
                )
                return 20
            self.generation_starts.append(cell.key)
            paths = artifacts(self.root, cell)
            paths.candidate.mkdir(parents=True)
            paths.log.write_text("GENERATION_DONE run_exit=0 wall_seconds=1\n", encoding="utf-8")
            return 0
        return await super()._process(cell, phase, stage_id)


def test_capacity_failure_is_retried_once_with_a_disclosed_ledger() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        value = manifest()
        value["execution"]["auto_retry"] = {
            "patterns": ["at capacity", "rate limit", "overloaded"],
            "backoff_seconds": 0,
        }
        path = write_manifest(root, value)
        cells = build_cells(value)
        flaky = next(cell for cell in cells if cell.model_slug == "a-fail")

        coordinator = FlakyCoordinator(
            path, provider_cap=1, model_cap=1, evaluation_cap=1, fail_key=flaky.key
        )
        result = asyncio.run(coordinator.run_stage("test-retry", cells))

        assert result.retried_generations == 1
        assert result.generation_failures == 0
        assert result.stopped_before_generation == 0
        assert coordinator.attempts[flaky.key] == 2
        assert cell_state(root, flaky) == "terminal"
        ledger = root / "incidents" / "auto-retry" / flaky.candidate_id / "incident.json"
        assert ledger.is_file()
        assert (
            ledger.parent / "attempt-1" / f"run-{flaky.task_suffix}-{flaky.candidate_id}.log"
        ).is_file()
        persisted = json.loads(path.read_text(encoding="utf-8"))
        retry = persisted["execution"]["infrastructure_retries"][flaky.candidate_id]
        assert retry["attempt"] == 2
        assert "at capacity" in retry["prior_failure"]
        assert retry["authorization_ledger"] == ledger.relative_to(root).as_posix()
        events = [
            json.loads(line)
            for line in (root / "scheduler-events.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert any(event["event"] == "generation-retry" for event in events)


def test_unmatched_agent_error_still_halts_admissions() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        value = manifest()
        value["execution"]["auto_retry"] = {"patterns": ["at capacity"], "backoff_seconds": 0}
        path = write_manifest(root, value)
        cells = build_cells(value)
        failed = next(cell for cell in cells if cell.model_slug == "a-fail")
        coordinator = FakeCoordinator(
            path, provider_cap=1, model_cap=1, evaluation_cap=1, fail_key=failed.key
        )
        result = asyncio.run(coordinator.run_stage("test-halt", cells))
        assert result.generation_failures == 1
        assert result.retried_generations == 0
        assert not (root / "incidents").exists()


def test_secret_scan_reports_path_without_value(tmp_path: Path) -> None:
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "run.log").write_text("leaked-secret-value", encoding="utf-8")

    assert secret_hits(tmp_path, ["leaked-secret-value"]) == ["logs/run.log"]


def test_secret_scan_ignores_short_placeholders(tmp_path: Path) -> None:
    (tmp_path / "report.json").write_text("test", encoding="utf-8")

    assert secret_hits(tmp_path, ["", "test"]) == []


def test_artifact_audit_verifies_telemetry_transcript_candidate_and_report(
    tmp_path: Path,
) -> None:
    value = official_manifest(tmp_path)
    cell = build_cells(value)[0]
    paths = artifacts(tmp_path, cell)
    paths.candidate.mkdir(parents=True)
    paths.sandbox.joinpath("raw").mkdir(parents=True)
    paths.log.parent.mkdir(parents=True)
    paths.report.parent.mkdir(parents=True)
    transcript = b'{"type":"result","subtype":"success"}\n'
    (paths.candidate / "agent-log.jsonl").write_bytes(transcript)
    (paths.sandbox / "raw" / "agent-log.jsonl").write_bytes(transcript)
    overlay = paths.candidate / "overlay"
    overlay.mkdir()
    (overlay / "app.py").write_text("app = object()\n", encoding="utf-8")
    paths.report.write_text(
        json.dumps(
            {
                "status": "failed",
                "provenance": {"candidate_digest": "sha256:" + "0" * 64},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (paths.candidate / "telemetry.json").write_text(
        json.dumps(
            {
                "schema": "sanka-bench/agent-cell-telemetry/v1",
                "input_digest": cell.input_digest,
                "digests": {
                    "transcript_sha256": "sha256:" + hashlib.sha256(transcript).hexdigest(),
                    "overlay_sha256": "sha256:" + "0" * 64,
                },
                "evaluation": {
                    "status": "passed",
                    "report_sha256": "sha256:"
                    + hashlib.sha256(paths.report.read_bytes()).hexdigest(),
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    paths.log.write_text(
        f"INPUT_DIGEST={cell.input_digest}\nDRIVER_DONE run_exit=0 eval_exit=0\n",
        encoding="utf-8",
    )

    issues = artifact_issues(tmp_path, [cell])

    assert any("overlay digest" in issue for issue in issues)
    assert any("candidate digest" in issue for issue in issues)
    assert any("evaluation status" in issue for issue in issues)
    assert not any("transcript digest" in issue for issue in issues)
    assert not any("report digest" in issue for issue in issues)

    telemetry = json.loads((paths.candidate / "telemetry.json").read_text(encoding="utf-8"))
    telemetry["digests"]["overlay_sha256"] = digest_tree(overlay)
    telemetry["evaluation"]["status"] = "failed"
    report = json.loads(paths.report.read_text(encoding="utf-8"))
    report["provenance"]["candidate_digest"] = digest_tree(paths.candidate)
    paths.report.write_text(json.dumps(report) + "\n", encoding="utf-8")
    telemetry["evaluation"]["report_sha256"] = (
        "sha256:" + hashlib.sha256(paths.report.read_bytes()).hexdigest()
    )
    (paths.candidate / "telemetry.json").write_text(json.dumps(telemetry) + "\n", encoding="utf-8")

    assert artifact_issues(tmp_path, [cell]) == []


def test_artifact_audit_requires_raw_evidence_for_failed_generation(tmp_path: Path) -> None:
    value = official_manifest(tmp_path)
    cell = build_cells(value)[0]
    paths = artifacts(tmp_path, cell)
    paths.log.parent.mkdir(parents=True)
    paths.log.write_text(
        f"INPUT_DIGEST={cell.input_digest}\nDRIVER_DONE run_exit=1 eval_exit=skipped\n",
        encoding="utf-8",
    )

    issues = artifact_issues(tmp_path, [cell])

    assert any("missing telemetry" in issue for issue in issues)
    assert any("missing transcript" in issue for issue in issues)
    assert not any("candidate overlay" in issue for issue in issues)


def test_artifact_audit_keeps_v1_results_readable(tmp_path: Path) -> None:
    cell = build_cells(manifest())[0]
    paths = artifacts(tmp_path, cell)
    paths.candidate.mkdir(parents=True)
    paths.report.parent.mkdir(parents=True)
    paths.report.write_text('{"status":"failed"}\n', encoding="utf-8")
    paths.log.parent.mkdir(parents=True)
    paths.log.write_text("DRIVER_DONE run_exit=0 eval_exit=0\n", encoding="utf-8")

    assert artifact_issues(tmp_path, [cell]) == []


def test_aggregate_refuses_secret_or_incomplete_artifacts(tmp_path: Path) -> None:
    value = official_manifest(tmp_path)
    value["execution"]["aggregate_command"] = [
        "{python}",
        "-c",
        "from pathlib import Path; Path('published').write_text('bad')",
    ]
    path = write_manifest(tmp_path, value)
    coordinator = RollingCoordinator(path, provider_cap=1, model_cap=1, evaluation_cap=1)
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "leak.log").write_text("sk-ant-this-is-a-secret", encoding="utf-8")

    assert coordinator.aggregate("blocked") != 0
    assert not (tmp_path / "published").exists()
    events = (tmp_path / "scheduler-events.jsonl").read_text(encoding="utf-8")
    assert "publication-gate-failed" in events
    assert "sk-ant-this-is-a-secret" not in events


def test_workflow_is_validated_and_invalidates_cached_cells(tmp_path: Path) -> None:
    value = official_manifest(tmp_path)
    old = build_cells(value)[0].input_digest
    value["execution"]["sanka_workflow"] = "artifacts-first-v1"
    validate_official_manifest(value, tmp_path)
    assert build_cells(value)[0].input_digest != old
    for threshold in (True, float("nan"), -1, 2):
        value["execution"]["sanka_readiness_threshold"] = threshold
        with pytest.raises(ValueError, match="threshold"):
            validate_official_manifest(value, tmp_path)
    value["execution"]["sanka_readiness_threshold"] = 0.5
    value["execution"]["sanka_workflow"] = "unknown"
    with pytest.raises(ValueError, match="workflow"):
        validate_official_manifest(value, tmp_path)


def test_comparison_keeps_regressions_missing_evidence_and_unverified_cost():
    from matrix_report import compare

    rows = [
        {
            "model_slug": "deepseek",
            "task": task,
            "sample": 1,
            "config": config,
            "route_weight": 1,
            "passed": True,
            "generation_seconds": seconds,
            "end_to_end_seconds": seconds + 1,
            "total_tokens": seconds,
            "cost_usd": None,
        }
        for config, seconds in [("alone", 10), ("sanka-cli", 5), ("with-sanka", 4)]
        for task in ["001", "002"]
    ]
    result = compare(rows)[1]
    assert result["goals"]["accuracy_at_least_baseline"] is True
    assert result["goals"]["faster_generation"] is True
    assert result["goals"]["lower_cost"] is None
    assert result["all_goals_met"] is None
    rows[2]["infrastructure_retries"] = 1
    assert compare(rows)[1]["goals"]["faster_generation"] is None
    rows[2]["infrastructure_retries"] = 0
    rows[2]["passed"] = False
    result = compare(rows)[1]
    assert result["paired_regressions"] == 1
    assert result["goals"]["accuracy_at_least_baseline"] is False
    assert result["all_goals_met"] is False
    rows[2]["passed"] = None
    result = compare(rows)[1]
    assert result["expected"] == 2 and result["scored"] == 1
    assert result["pass_at_1"] is None
    assert result["goals"]["accuracy_at_least_baseline"] is None


def test_artifacts_first_auto_report_keeps_unscored_rows_and_blocks_secrets(tmp_path):
    value = official_manifest(tmp_path)
    value["execution"]["sanka_workflow"] = "artifacts-first-v1"
    path = write_manifest(tmp_path, value)
    coordinator = RollingCoordinator(path, provider_cap=1, model_cap=1, evaluation_cap=1)
    assert coordinator.aggregate("unscored") == 0
    report = json.loads((tmp_path / "matrix.json").read_text())
    assert len(report["rows"]) == 2
    assert all(row["passed"] is None for row in report["rows"])
    assert report["comparisons"][1]["all_goals_met"] is None
    prior = (tmp_path / "matrix.json").read_bytes()
    (tmp_path / "leak.log").write_text("sk-ant-this-is-a-secret")
    assert coordinator.aggregate("blocked") != 0
    assert (tmp_path / "matrix.json").read_bytes() == prior
