from __future__ import annotations

import hashlib
import importlib.util
import json
import os
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
            "wall_clock_seconds": 900,
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


def test_each_cell_has_an_isolated_persistent_sandbox(driver: object, tmp_path: Path) -> None:
    manifest = _manifest(samples=1)
    first = driver.resolve_cell(manifest, "001", "sonnet5", "alone", 1)  # type: ignore[attr-defined]
    second = driver.resolve_cell(manifest, "007", "sonnet5", "alone", 1)  # type: ignore[attr-defined]

    first_paths = driver.resolve_paths(tmp_path / "run-manifest.json", manifest, first)  # type: ignore[attr-defined]
    second_paths = driver.resolve_paths(tmp_path / "run-manifest.json", manifest, second)  # type: ignore[attr-defined]

    assert first_paths.sandbox == tmp_path / "sandboxes" / first.candidate_id
    assert first_paths.claude_config == first_paths.sandbox / "claude-config"
    assert first_paths.sanka_home == first_paths.sandbox / "sanka-home"
    assert first_paths.sandbox != second_paths.sandbox


@pytest.mark.parametrize("workflow", ["artifacts-first-v1", "artifacts-first-v2"])
def test_v2_generation_command_passes_route_and_sandbox_metadata(
    driver: object, tmp_path: Path, workflow: str
) -> None:
    manifest = _manifest(samples=1)
    manifest["execution"]["sanka_workflow"] = workflow
    manifest["execution"]["sanka_readiness_threshold"] = 0.75
    manifest["schema"] = "sanka-bench/model-matrix-run-manifest/v2"
    manifest["execution"]["configurations"] = ["alone", "with-sanka"]  # type: ignore[index]
    manifest["models"] = [
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
    manifest["toolchain"]["sanka_skill_sha256"] = "sha256:" + "a" * 64  # type: ignore[index]
    cell = driver.resolve_cell(manifest, "001", "gpt56", "alone", 1)  # type: ignore[attr-defined]
    paths = driver.resolve_paths(tmp_path / "run-manifest.json", manifest, cell)  # type: ignore[attr-defined]
    tools = {
        "python": tmp_path / "python",
        "agent_runner": tmp_path / "run_agent_candidate.py",
        "claude": tmp_path / "claude",
    }

    command = driver.generation_command(  # type: ignore[attr-defined]
        manifest, cell, paths, tools, attempt=1, prior_failure=None
    )

    assert command[command.index("--sanka-workflow") + 1] == workflow
    assert command[command.index("--sanka-readiness-threshold") + 1] == "0.75"
    assert command[command.index("--sandbox") + 1] == str(paths.sandbox)
    assert command[command.index("--actual-model-id") + 1] == cell.actual_model_id
    assert command[command.index("--route-kind") + 1] == "gateway"
    assert command[command.index("--billing-mode") + 1] == "api_key"
    assert command[command.index("--wall-clock-seconds") + 1] == "900"
    assert command[command.index("--gateway-profile") + 1] == "cliproxyapi-anthropic-v1"

    with_sanka = driver.resolve_cell(  # type: ignore[attr-defined]
        manifest, "001", "gpt56", "with-sanka", 1
    )
    tools["sanka"] = tmp_path / "sanka"
    command = driver.generation_command(  # type: ignore[attr-defined]
        manifest, with_sanka, paths, tools, attempt=1, prior_failure=None
    )
    assert command[command.index("--sanka-skill-sha256") + 1] == "sha256:" + "a" * 64


def test_native_subscription_prerequisites_do_not_require_an_env_file(
    driver: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest(samples=1)
    manifest["schema"] = "sanka-bench/model-matrix-run-manifest/v2"
    manifest["execution"]["configurations"] = ["alone", "with-sanka"]  # type: ignore[index]
    manifest["models"] = [
        {
            "slug": "sonnet5",
            "candidate_slug": "claude-code-sonnet5",
            "harness": "claude-code",
            "provider": "anthropic",
            "requested_model_id": "claude-sonnet-5",
            "actual_model_id": "claude-sonnet-5-20260901",
            "route_kind": "anthropic-native",
            "billing_mode": "subscription",
        }
    ]
    worktree = tmp_path / "bench"
    task = worktree / "tasks" / "drf-fastapi" / "drf-fastapi-001"
    (task / "source").mkdir(parents=True)
    (task / "public-tests").mkdir()
    (task / "public-tests" / "scenarios.json").write_text("[]\n", encoding="utf-8")
    for relative in (".venv/bin/python", ".venv/bin/sanka-bench"):
        path = worktree / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    claude = worktree / "claude"
    claude.write_text("#!/bin/sh\necho 2.1.241\n", encoding="utf-8")
    claude.chmod(0o755)
    runner = worktree / "scripts" / "run_agent_candidate.py"
    runner.parent.mkdir()
    runner.write_text("# runner\n", encoding="utf-8")
    manifest["toolchain"] = {
        "worktree": str(worktree),
        "claude_bin": str(claude),
        "claude_version": "2.1.241",
        "claude_bin_sha256": "sha256:" + hashlib.sha256(claude.read_bytes()).hexdigest(),
        "agent_runner_sha256": hashlib.sha256(runner.read_bytes()).hexdigest(),
    }
    monkeypatch.setattr(
        driver.subprocess,  # type: ignore[attr-defined]
        "check_output",
        lambda *_args, **_kwargs: manifest["benchmark_sha"],
    )
    cell = driver.resolve_cell(manifest, "001", "sonnet5", "alone", 1)  # type: ignore[attr-defined]
    paths = driver.resolve_paths(tmp_path / "run-manifest.json", manifest, cell)  # type: ignore[attr-defined]

    tools = driver.validate_prerequisites(manifest, cell, paths)  # type: ignore[attr-defined]

    assert "env" not in tools

    claude.write_text("#!/bin/sh\necho changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Claude binary digest"):
        driver.validate_prerequisites(manifest, cell, paths)  # type: ignore[attr-defined]


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
    assert command[command.index("--provider") + 1] == "anthropic"


def test_cli_only_arm_gets_sanka_without_the_skill_digest(driver: object, tmp_path: Path) -> None:
    manifest = _manifest(samples=1)
    manifest["schema"] = "sanka-bench/model-matrix-run-manifest/v2"
    manifest["execution"]["configurations"] = ["alone", "sanka-cli", "with-sanka"]  # type: ignore[index]
    manifest["models"] = [manifest["models"][0]]  # type: ignore[index]
    manifest["toolchain"]["sanka_skill_sha256"] = "sha256:" + "a" * 64  # type: ignore[index]
    tools = {
        "python": tmp_path / "python",
        "agent_runner": tmp_path / "run_agent_candidate.py",
        "claude": tmp_path / "claude",
        "sanka": tmp_path / "sanka",
    }
    cell = driver.resolve_cell(manifest, "001", "sonnet5", "sanka-cli", 1)  # type: ignore[attr-defined]
    paths = driver.resolve_paths(tmp_path / "run-manifest.json", manifest, cell)  # type: ignore[attr-defined]

    command = driver.generation_command(  # type: ignore[attr-defined]
        manifest, cell, paths, tools, attempt=1, prior_failure=None
    )

    assert command[command.index("--sanka-bin") + 1] == str(tmp_path / "sanka")
    assert "--sanka-skill-sha256" not in command


def test_evaluation_command_uses_the_manifest_container_engine(
    driver: object, tmp_path: Path
) -> None:
    manifest = _manifest(samples=1)
    manifest["execution"]["container_engine"] = "podman"  # type: ignore[index]
    cell = driver.resolve_cell(manifest, "001", "sonnet5", "alone", 1)  # type: ignore[attr-defined]
    paths = driver.resolve_paths(tmp_path / "run-manifest.json", manifest, cell)  # type: ignore[attr-defined]

    command = driver.evaluation_command(  # type: ignore[attr-defined]
        manifest, cell, paths, {"bench": tmp_path / "sanka-bench"}
    )

    assert command[:5] == [
        str(tmp_path / "sanka-bench"),
        "evaluate",
        "--runner",
        "docker",
        "--container-engine",
    ]
    assert command[5] == "podman"


def test_evaluation_environment_can_find_the_selected_container_engine(
    driver: object, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    engine_dir = tmp_path / "homebrew" / "bin"
    engine_dir.mkdir(parents=True)
    engine = engine_dir / "podman"
    engine.write_text("#!/bin/sh\n", encoding="utf-8")
    engine.chmod(0o755)
    monkeypatch.setenv("PATH", f"{engine_dir}:/usr/bin:/bin")
    manifest = _manifest(samples=1)
    manifest["execution"]["container_engine"] = "podman"  # type: ignore[index]

    environment = driver.evaluation_environment(manifest)  # type: ignore[attr-defined]

    assert environment["PATH"] == f"{engine_dir}{os.pathsep}{os.defpath}"


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
        'OPENAI_API_KEY="sk-test"\nFIREWORKS_API_KEY=fw-test\n'
        "ANTHROPIC_BASE_URL=https://gateway.test\nANTHROPIC_AUTH_TOKEN=token\n"
        "SECRET_OTHER=nope\n# c=1\n",
        encoding="utf-8",
    )
    values = driver.read_allowlisted_env(env_file)  # type: ignore[attr-defined]
    assert values == {
        "OPENAI_API_KEY": "sk-test",
        "FIREWORKS_API_KEY": "fw-test",
        "ANTHROPIC_BASE_URL": "https://gateway.test",
        "ANTHROPIC_AUTH_TOKEN": "token",
    }
    assert json.dumps(values)  # serialisable for the toolchain record


def test_route_environment_separates_subscription_and_gateway(driver: object) -> None:
    manifest = _manifest(samples=1)
    native = driver.resolve_cell(manifest, "001", "sonnet5", "alone", 1)  # type: ignore[attr-defined]
    object.__setattr__(native, "route_kind", "anthropic-native")
    object.__setattr__(native, "billing_mode", "subscription")
    gateway = driver.resolve_cell(manifest, "001", "sonnet5", "alone", 1)  # type: ignore[attr-defined]
    object.__setattr__(gateway, "route_kind", "gateway")
    object.__setattr__(gateway, "billing_mode", "api_key")
    base = {
        "PATH": "/bin",
        "ANTHROPIC_BASE_URL": "https://gateway.test",
        "ANTHROPIC_AUTH_TOKEN": "token",
        "OPENAI_API_KEY": "unrelated",
    }

    assert driver.route_environment(base, native) == {"PATH": "/bin"}  # type: ignore[attr-defined]
    assert driver.route_environment(base, gateway) == {
        "PATH": "/bin",
        "ANTHROPIC_BASE_URL": "https://gateway.test",
        "ANTHROPIC_AUTH_TOKEN": "token",
    }  # type: ignore[attr-defined]
    with pytest.raises(ValueError, match="exactly one credential"):
        driver.route_environment(  # type: ignore[attr-defined]
            {**base, "ANTHROPIC_API_KEY": "second"}, gateway
        )
    with pytest.raises(ValueError, match="base URL"):
        driver.route_environment({"ANTHROPIC_AUTH_TOKEN": "token"}, gateway)  # type: ignore[attr-defined]


def test_official_generation_requires_the_coordinator_input_digest(
    driver: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest(samples=1)
    manifest["schema"] = "sanka-bench/model-matrix-run-manifest/v2"
    monkeypatch.delenv("SANKA_BENCH_INPUT_DIGEST", raising=False)
    with pytest.raises(ValueError, match="input digest"):
        driver.required_input_digest(manifest)  # type: ignore[attr-defined]

    expected = "sha256:" + "a" * 64
    monkeypatch.setenv("SANKA_BENCH_INPUT_DIGEST", expected)
    assert driver.required_input_digest(manifest) == expected  # type: ignore[attr-defined]
    assert driver.required_input_digest(_manifest(samples=1)) is None  # type: ignore[attr-defined]


def test_cell_telemetry_updates_are_merged_atomically(driver: object, tmp_path: Path) -> None:
    manifest = _manifest(samples=1)
    cell = driver.resolve_cell(manifest, "001", "sonnet5", "alone", 1)  # type: ignore[attr-defined]
    paths = driver.resolve_paths(tmp_path / "run-manifest.json", manifest, cell)  # type: ignore[attr-defined]
    paths.candidate.mkdir(parents=True)
    telemetry = paths.candidate / "telemetry.json"
    telemetry.write_text(
        json.dumps(
            {
                "schema": "sanka-bench/agent-cell-telemetry/v1",
                "timing": {"agent_wall_seconds": 1.0},
            }
        ),
        encoding="utf-8",
    )

    driver.update_cell_telemetry(  # type: ignore[attr-defined]
        paths,
        timing={"generation_seconds": 1.5, "setup_seconds": 0.5},
        wave={"id": "wave-1", "admitted_concurrency": 2},
    )
    driver.update_cell_telemetry(  # type: ignore[attr-defined]
        paths,
        timing={"evaluation_seconds": 0.25},
        evaluation={"status": "passed", "report_sha256": "sha256:" + "a" * 64},
        failure_class=None,
    )

    payload = json.loads(telemetry.read_text(encoding="utf-8"))
    assert payload["timing"] == {
        "agent_wall_seconds": 1.0,
        "generation_seconds": 1.5,
        "setup_seconds": 0.5,
        "evaluation_seconds": 0.25,
    }
    assert payload["wave"]["id"] == "wave-1"
    assert payload["evaluation"]["status"] == "passed"
    assert payload["failure_class"] is None
    assert not telemetry.with_suffix(".json.tmp").exists()


def test_evaluation_timing_is_copied_into_the_result(driver: object, tmp_path: Path) -> None:
    manifest = _manifest(samples=1)
    cell = driver.resolve_cell(manifest, "001", "sonnet5", "alone", 1)  # type: ignore[attr-defined]
    paths = driver.resolve_paths(tmp_path / "run-manifest.json", manifest, cell)  # type: ignore[attr-defined]
    paths.candidate.mkdir(parents=True)
    paths.report.parent.mkdir(parents=True)
    (paths.candidate / "telemetry.json").write_text(
        json.dumps(
            {
                "timing": {
                    "generation_seconds": 12.0,
                    "setup_seconds": 2.0,
                }
            }
        ),
        encoding="utf-8",
    )
    paths.report.write_text(
        json.dumps({"provenance": {"candidate_stats": {"duration_seconds": 10.0}}}),
        encoding="utf-8",
    )

    driver.update_report_timing(paths, 3.0)  # type: ignore[attr-defined]

    stats = json.loads(paths.report.read_text(encoding="utf-8"))["provenance"]["candidate_stats"]
    assert stats == {
        "duration_seconds": 10.0,
        "setup_seconds": 2.0,
        "evaluation_seconds": 3.0,
        "end_to_end_seconds": 15.0,
    }


def test_flask_lane_selects_its_own_extension_distribution(driver, monkeypatch):
    manifest = _manifest(samples=1)
    manifest["suite"]["tasks"] = ["drf-flask-004"]
    manifest["toolchain"].update(sanka_cli="sanka-cli test", extension_version="0.1.0a1")
    observed = []

    def versions(binary, distribution):
        observed.append(distribution)
        return "sanka-cli test", "0.1.0a1"

    monkeypatch.setattr(driver, "sanka_versions", versions)
    driver.check_sanka_toolchain(manifest, Path("/tools/sanka"))
    assert observed == ["sanka-extension-drf-to-flask"]


def test_codex_openai_route_only_inherits_platform_key_and_explicit_effort(
    driver: object, tmp_path: Path
) -> None:
    manifest = _manifest(samples=1)
    model = manifest["models"][1]
    model.update(route_kind="openai-responses", billing_mode="api_key", reasoning_effort="high")
    cell = driver.resolve_cell(manifest, "001", "gpt56sol", "alone", 1)  # type: ignore[attr-defined]
    env = driver.route_environment(
        {
            "OPENAI_API_KEY": "platform-test",
            "FIREWORKS_API_KEY": "other",  # type: ignore[attr-defined]
            "ANTHROPIC_AUTH_TOKEN": "subscription",
            "PATH": "/usr/bin",
        },
        cell,
    )
    assert env == {"OPENAI_API_KEY": "platform-test", "PATH": "/usr/bin"}
    paths = driver.resolve_paths(tmp_path / "run-manifest.json", manifest, cell)  # type: ignore[attr-defined]
    tools = {"python": Path("python"), "agent_runner": Path("runner"), "codex": Path("codex")}
    command = driver.generation_command(manifest, cell, paths, tools, attempt=1, prior_failure=None)  # type: ignore[attr-defined]
    assert command[command.index("--reasoning-effort") + 1] == "high"
    assert "--max-budget-usd" not in command


def test_native_cell_needs_no_agent_binary_and_strips_other_provider_keys(driver, tmp_path):
    manifest = _manifest(samples=1)
    model = manifest["models"][1]
    model.update(
        agent="sanka-native",
        provider="fireworks",
        route_kind="openai-chat",
        billing_mode="api_key",
        reasoning_effort="high",
        price_in=0.1,
        price_out=0.2,
    )
    manifest["execution"]["sanka_workflow"] = "native-lifecycle-v1"
    manifest["execution"]["max_output_tokens"] = 32768
    cell = driver.resolve_cell(manifest, "001", "gpt56sol", "alone", 1)
    env = driver.route_environment(
        {"FIREWORKS_API_KEY": "selected", "OPENAI_API_KEY": "other"}, cell
    )
    assert env == {"FIREWORKS_API_KEY": "selected"}
    paths = driver.resolve_paths(tmp_path / "run-manifest.json", manifest, cell)
    command = driver.generation_command(
        manifest,
        cell,
        paths,
        {"python": Path("python"), "agent_runner": Path("runner")},
        attempt=1,
        prior_failure=None,
    )
    assert "--agent-bin" not in command
    assert command[command.index("--agent") + 1] == "sanka-native"
    assert command[command.index("--price-in") + 1] == "0.1"
    assert command[command.index("--max-output-tokens") + 1] == "32768"
