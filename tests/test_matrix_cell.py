from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name: str) -> object:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def driver() -> object:
    return _load("run_matrix_cell")


@pytest.fixture(scope="module")
def runner() -> object:
    return _load("run_agent_matrix")


def _manifest(samples: int) -> dict[str, object]:
    return {
        "suite": {
            "tasks": ["drf-fastapi-001", "drf-fastapi-007"],
            "route_weights": {"drf-fastapi-001": 7, "drf-fastapi-007": 14},
        },
        "execution": {
            "configurations": ["alone", "with-sanka-readiness-aware"],
            "samples": samples,
            "expected_rows": 2 * 2 * 2 * samples,
            "max_turns": 120,
            "authorization_scope": f"{2 * 2 * 2 * samples}-cell-v1",
        },
        "models": [
            {
                "slug": "sonnet5",
                "candidate_slug": "claude-sonnet5",
                "agent": "claude-code",
                "provider": "anthropic",
                "model_id": "claude-sonnet-5",
            },
            {
                "slug": "gpt56sol",
                "candidate_slug": "codex-gpt-5-6-sol",
                "agent": "codex",
                "provider": "openai",
                "model_id": "gpt-5.6-sol",
            },
        ],
        "toolchain": {"worktree": "/bench"},
        "benchmark_sha": "0" * 40,
        "authorization": {
            "paid_run_authorized": True,
            "authorization_scope": f"{2 * 2 * 2 * samples}-cell-v1",
            "run_id": "v1-test",
        },
    }


def test_cell_identity_matches_the_coordinator(driver: object, runner: object) -> None:
    manifest = _manifest(samples=3)
    cells = runner.build_cells(manifest)  # type: ignore[attr-defined]
    ids = {cell.candidate_id for cell in cells}
    assert len(cells) == 24
    for cell in cells:
        resolved = driver.resolve_cell(  # type: ignore[attr-defined]
            manifest, cell.task, cell.model_slug, cell.config, cell.sample
        )
        assert resolved.candidate_id == cell.candidate_id
        assert resolved.candidate_id in ids
    single = driver.resolve_cell(  # type: ignore[attr-defined]
        _manifest(samples=1), "001", "sonnet5", "alone", 1
    )
    assert single.candidate_id == "drf-fastapi-001-claude-sonnet5-alone"
    with pytest.raises(ValueError):
        driver.resolve_cell(_manifest(samples=1), "001", "sonnet5", "alone", 2)  # type: ignore[attr-defined]


def test_v2_cell_carries_harness_and_route_treatment(driver: object) -> None:
    value = _manifest(samples=1)
    value["schema"] = "sanka-bench/model-matrix-run-manifest/v2"
    value["execution"]["configurations"] = ["alone", "with-sanka"]  # type: ignore[index]
    value["execution"]["expected_rows"] = 4  # type: ignore[index]
    value["models"] = [
        {
            "slug": "gpt56",
            "candidate_slug": "claude-code-gpt-5-6",
            "harness": "claude-code",
            "provider": "openai",
            "provider_variant": "cliproxyapi",
            "requested_model_id": "gpt-5.6",
            "actual_model_id": "gpt-5.6-20260901",
            "route_kind": "gateway",
            "billing_mode": "api_key",
            "gateway_profile": "cliproxyapi-anthropic-v1",
        }
    ]

    cell = driver.resolve_cell(value, "001", "gpt56", "alone", 1)  # type: ignore[attr-defined]

    assert cell.agent == "claude-code"
    assert cell.model_id == "gpt-5.6"
    assert cell.actual_model_id == "gpt-5.6-20260901"
    assert cell.route_kind == "gateway"
    assert cell.billing_mode == "api_key"
    assert cell.gateway_profile == "cliproxyapi-anthropic-v1"


def test_generation_command_offers_sanka_only_to_with_sanka_cells(
    driver: object, tmp_path: Path
) -> None:
    manifest = _manifest(samples=3)
    tools = {
        "python": tmp_path / "python",
        "agent_runner": tmp_path / "run_agent_candidate.py",
        "claude": tmp_path / "claude",
        "codex": tmp_path / "codex",
        "sanka": tmp_path / "sanka",
    }
    alone = driver.resolve_cell(manifest, "drf-fastapi-007", "gpt56sol", "alone", 2)  # type: ignore[attr-defined]
    paths = driver.resolve_paths(tmp_path / "run-manifest.json", manifest, alone)  # type: ignore[attr-defined]
    command = driver.generation_command(  # type: ignore[attr-defined]
        manifest, alone, paths, tools, attempt=1, prior_failure=None
    )
    assert "--sanka-bin" not in command
    assert command[command.index("--provider") + 1] == "openai"
    assert (
        command[command.index("--candidate-id") + 1] == "drf-fastapi-007-codex-gpt-5-6-sol-alone-s2"
    )
    assert command[command.index("--max-turns") + 1] == "120"
    assert paths.candidate == tmp_path / "candidates" / "drf-fastapi-007" / alone.candidate_id
    assert paths.log == tmp_path / "logs" / f"run-007-{alone.candidate_id}.log"

    sanka = driver.resolve_cell(  # type: ignore[attr-defined]
        manifest, "drf-fastapi-001", "sonnet5", "with-sanka-readiness-aware", 3
    )
    command = driver.generation_command(  # type: ignore[attr-defined]
        manifest, sanka, paths, tools, attempt=1, prior_failure=None
    )
    assert command[command.index("--sanka-bin") + 1] == str(tmp_path / "sanka")
    assert "--provider" not in command


def test_generation_requires_the_authorized_coordinator(
    driver: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest(samples=1)
    monkeypatch.delenv("SANKA_BENCH_COORDINATOR_RUN_ID", raising=False)
    with pytest.raises(ValueError, match="foreground coordinator"):
        driver.ensure_generation_authorized(manifest)  # type: ignore[attr-defined]
    monkeypatch.setenv("SANKA_BENCH_COORDINATOR_RUN_ID", "v1-test")
    driver.ensure_generation_authorized(manifest)  # type: ignore[attr-defined]
    manifest["authorization"]["authorization_scope"] = "other"  # type: ignore[index]
    with pytest.raises(ValueError, match="scope"):
        driver.ensure_generation_authorized(manifest)  # type: ignore[attr-defined]


def test_markers_written_by_the_driver_read_back_as_terminal(
    driver: object, runner: object, tmp_path: Path
) -> None:
    manifest = _manifest(samples=3)
    cells = runner.build_cells(manifest)  # type: ignore[attr-defined]
    cell = cells[0]
    paths = runner.artifacts(tmp_path, cell)  # type: ignore[attr-defined]
    paths.candidate.mkdir(parents=True)
    paths.report.parent.mkdir(parents=True)
    paths.report.write_text("{}", encoding="utf-8")
    driver.append_line(paths.log, "GENERATION_DONE run_exit=0 wall_seconds=10")  # type: ignore[attr-defined]
    assert runner.cell_state(tmp_path, cell) == "ambiguous"  # type: ignore[attr-defined]
    paths.report.unlink()
    assert runner.cell_state(tmp_path, cell) == "generated"  # type: ignore[attr-defined]
    paths.report.write_text("{}", encoding="utf-8")
    driver.append_line(  # type: ignore[attr-defined]
        paths.log,
        f"DRIVER_DONE task={cell.task} cid={cell.candidate_id} run_exit=0 eval_exit=0 "
        "wall_seconds=recorded",
    )
    assert runner.cell_state(tmp_path, cell) == "terminal"  # type: ignore[attr-defined]


def test_allowlisted_env_reads_only_provider_keys(driver: object, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        'OPENAI_API_KEY="sk-test"\nFIREWORKS_API_KEY=fw-test\nSECRET_OTHER=nope\n# c=1\n',
        encoding="utf-8",
    )
    values = driver.read_allowlisted_env(env_file)  # type: ignore[attr-defined]
    assert values == {"OPENAI_API_KEY": "sk-test", "FIREWORKS_API_KEY": "fw-test"}
    assert json.dumps(values)  # serialisable for the toolchain record
