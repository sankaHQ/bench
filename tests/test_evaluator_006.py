from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sanka_bench.evaluator import evaluate_local
from sanka_bench.hashing import digest_tree
from sanka_bench.schema import load_and_validate


@pytest.fixture(scope="session")
def task_006_dir(repository_root: Path) -> Path:
    return repository_root / "tasks" / "drf-fastapi" / "drf-fastapi-006"


@pytest.fixture(scope="module")
def baseline_006_results(repository_root: Path, task_006_dir: Path) -> dict[str, dict[str, Any]]:
    return {
        name: evaluate_local(task_006_dir, repository_root / "baselines" / "drf-fastapi-006" / name)
        for name in ("noop", "compatibility-bridge", "native-reference", "sanka-native")
    }


def test_source_digest_is_pinned_to_fixture(task_006_dir: Path) -> None:
    task = load_and_validate(task_006_dir / "task.yaml", "task")
    assert task["source"]["provenance"]["digest"] == digest_tree(task_006_dir / "source")


def test_public_scenarios_are_a_strict_subset_of_the_graded_set(task_006_dir: Path) -> None:
    """The visible cases establish the graph shape; hidden cases pin depth-two
    error indexes, replacement semantics, and rollback at later children."""
    public = json.loads(
        (task_006_dir / "public-tests" / "scenarios.json").read_text(encoding="utf-8")
    )
    graded = json.loads(
        (task_006_dir / "evaluation" / "scenarios.json").read_text(encoding="utf-8")
    )
    public_ids = [scenario["id"] for scenario in public]
    graded_ids = [scenario["id"] for scenario in graded]
    assert len(public_ids) == 7
    assert len(graded_ids) == 32
    assert public == graded[: len(public)]
    assert set(public_ids) < set(graded_ids)
    assert {
        "create-invalid-second-item-second-adjustment",
        "create-duplicate-item-sku-rolls-back",
        "create-duplicate-adjustment-in-second-item-rolls-back",
        "put-duplicate-adjustment-in-second-item-rolls-back",
        "patch-reference-only-preserves-graph",
        "patch-empty-items-clears-graph",
        "patch-missing-nested-field-rejected",
        "patch-duplicate-adjustment-rolls-back",
    } <= set(graded_ids) - set(public_ids)
    task = load_and_validate(task_006_dir / "task.yaml", "task")
    assert task["evaluation"]["scenarios"] == "evaluation/scenarios.json"


def test_noop_fails_without_a_target(baseline_006_results: dict[str, dict[str, Any]]) -> None:
    result = baseline_006_results["noop"]
    assert result["status"] == "failed"
    assert result["hard_gates"]["source_qualified"] is True
    assert result["hard_gates"]["target_boot"] is False
    assert result["hard_gates"]["native_target"] is False


def test_bridge_preserves_graph_behavior_but_fails_native_gate(
    baseline_006_results: dict[str, dict[str, Any]],
) -> None:
    result = baseline_006_results["compatibility-bridge"]
    assert result["hard_gates"]["behavior_parity"] is True
    assert result["hard_gates"]["database_parity"] is True
    assert result["hard_gates"]["side_effect_parity"] is True
    assert result["hard_gates"]["native_target"] is False
    assert result["fully_migrated"] is False
    evidence = result["scenarios"][0]["native"]
    assert "rest_framework" in evidence["forbidden_imports"]


def test_native_reference_passes_every_hard_gate(
    baseline_006_results: dict[str, dict[str, Any]],
) -> None:
    result = baseline_006_results["native-reference"]
    assert result["status"] == "passed"
    assert result["fully_migrated"] is True
    assert all(result["hard_gates"].values())
    assert result["metrics"]["scenario_count"] == 32
    assert result["errors"] == []
    for scenario in result["scenarios"]:
        evidence = scenario["native"]
        assert evidence["forbidden_imports"] == []
        assert evidence["settings_module"] == "target_settings"


def test_sanka_native_records_the_readiness_abstention(
    baseline_006_results: dict[str, dict[str, Any]],
) -> None:
    """Only the API root is generatable, leaving readiness below the default
    threshold, so apply emits a gap report instead of an overlay."""
    result = baseline_006_results["sanka-native"]
    assert result["candidate_id"] == "sanka-native"
    assert result["status"] == "failed"
    assert result["fully_migrated"] is False
    assert result["hard_gates"]["source_qualified"] is True
    assert result["hard_gates"]["regression_tests"] is True
    assert result["hard_gates"]["target_boot"] is False
    assert result["hard_gates"]["behavior_parity"] is False
    assert result["hard_gates"]["database_parity"] is False
    assert result["hard_gates"]["native_target"] is False
    assert result["metrics"]["behavioral_parity"]["passed"] == 0
    assert result["metrics"]["database_parity"]["passed"] == 0
    assert result["metrics"]["native_compliance"]["passed"] == 0
