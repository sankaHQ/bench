from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sanka_bench.evaluator import evaluate_local
from sanka_bench.hashing import digest_tree
from sanka_bench.schema import load_and_validate


@pytest.fixture(scope="session")
def task_003_dir(repository_root: Path) -> Path:
    return repository_root / "tasks" / "drf-fastapi" / "drf-fastapi-003"


@pytest.fixture(scope="module")
def baseline_003_results(repository_root: Path, task_003_dir: Path) -> dict[str, dict[str, Any]]:
    return {
        name: evaluate_local(task_003_dir, repository_root / "baselines" / "drf-fastapi-003" / name)
        for name in ("noop", "compatibility-bridge", "native-reference", "sanka-native")
    }


def test_source_digest_is_pinned_to_fixture(task_003_dir: Path) -> None:
    task = load_and_validate(task_003_dir / "task.yaml", "task")
    assert task["source"]["provenance"]["digest"] == digest_tree(task_003_dir / "source")


def test_noop_fails_without_a_target(baseline_003_results: dict[str, dict[str, Any]]) -> None:
    result = baseline_003_results["noop"]
    assert result["status"] == "failed"
    assert result["hard_gates"]["source_qualified"] is True
    assert result["hard_gates"]["native_target"] is False


def test_bridge_preserves_nested_behavior_but_fails_native_gate(
    baseline_003_results: dict[str, dict[str, Any]],
) -> None:
    result = baseline_003_results["compatibility-bridge"]
    assert result["hard_gates"]["behavior_parity"] is True
    assert result["hard_gates"]["database_parity"] is True
    assert result["hard_gates"]["native_target"] is False
    assert result["fully_migrated"] is False
    evidence = result["scenarios"][0]["native"]
    assert "rest_framework" in evidence["forbidden_imports"]


def test_native_reference_passes_every_hard_gate(
    baseline_003_results: dict[str, dict[str, Any]],
) -> None:
    result = baseline_003_results["native-reference"]
    assert result["status"] == "passed"
    assert result["fully_migrated"] is True
    assert all(result["hard_gates"].values())
    assert result["metrics"]["scenario_count"] == 16
    assert result["errors"] == []


def test_sanka_native_converter_passes_the_nested_fixture(
    baseline_003_results: dict[str, dict[str, Any]],
) -> None:
    """The converter's untouched output, with the author's create() carried
    over verbatim — transaction boundary, business rule, rollback and all."""
    result = baseline_003_results["sanka-native"]
    assert result["candidate_id"] == "sanka-native"
    assert result["status"] == "passed"
    assert result["fully_migrated"] is True
    assert all(result["hard_gates"].values())
    assert result["errors"] == []
    for scenario in result["scenarios"]:
        evidence = scenario["native"]
        assert evidence["forbidden_imports"] == []
        assert evidence["settings_module"] == "sanka_settings"


def test_rollback_scenario_compares_database_state(task_003_dir: Path) -> None:
    """The rollback contract is observable: the scenario exists and the
    fixture's own test suite pins that a failed business rule leaves no
    partial rows, so a non-atomic candidate fails database parity."""
    scenarios = json.loads(
        (task_003_dir / "public-tests" / "scenarios.json").read_text(encoding="utf-8")
    )
    ids = {scenario["id"] for scenario in scenarios}
    assert {
        "create-rollback-on-business-rule",
        "create-nested-item-invalid",
        "create-duplicate-reference",
        "create-price-too-many-decimals",
        "create-items-not-a-list",
    } <= ids
