from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sanka_bench.evaluator import evaluate_local
from sanka_bench.hashing import digest_tree
from sanka_bench.schema import load_and_validate


@pytest.fixture(scope="session")
def task_010_dir(repository_root: Path) -> Path:
    return repository_root / "tasks" / "drf-fastapi" / "drf-fastapi-010"


@pytest.fixture(scope="module")
def baseline_010_results(repository_root: Path, task_010_dir: Path) -> dict[str, dict[str, Any]]:
    return {
        name: evaluate_local(task_010_dir, repository_root / "baselines" / "drf-fastapi-010" / name)
        for name in ("noop", "compatibility-bridge", "native-reference", "sanka-native")
    }


def test_source_digest_is_pinned_to_fixture(task_010_dir: Path) -> None:
    task = load_and_validate(task_010_dir / "task.yaml", "task")
    assert task["source"]["provenance"]["digest"] == digest_tree(task_010_dir / "source")


def test_public_scenarios_are_a_strict_subset_of_the_graded_set(task_010_dir: Path) -> None:
    """The public seven expose basic locking; hidden cases exhaust the full
    state-transition matrix plus invalid-target and stale-transition rollback."""
    public = json.loads(
        (task_010_dir / "public-tests" / "scenarios.json").read_text(encoding="utf-8")
    )
    graded = json.loads(
        (task_010_dir / "evaluation" / "scenarios.json").read_text(encoding="utf-8")
    )
    public_ids = [scenario["id"] for scenario in public]
    graded_ids = [scenario["id"] for scenario in graded]
    assert len(public_ids) == 7
    assert len(graded_ids) == 32
    assert public == graded[: len(public)]
    assert set(public_ids) < set(graded_ids)
    hidden_ids = set(graded_ids) - set(public_ids)
    assert {
        "transition-draft-to-cancelled",
        "transition-submitted-to-approved",
        "transition-submitted-to-cancelled",
        "transition-approved-to-shipped",
        "transition-shipped-to-cancelled",
        "transition-cancelled-to-draft",
        "unknown-transition-target-validation",
        "stale-transition-rolls-back-both-tables",
    } <= hidden_ids
    task = load_and_validate(task_010_dir / "task.yaml", "task")
    assert task["evaluation"]["scenarios"] == "evaluation/scenarios.json"


def test_noop_fails_without_a_target(baseline_010_results: dict[str, dict[str, Any]]) -> None:
    result = baseline_010_results["noop"]
    assert result["status"] == "failed"
    assert result["hard_gates"]["source_qualified"] is True
    assert result["hard_gates"]["target_boot"] is False
    assert result["hard_gates"]["native_target"] is False


def test_bridge_preserves_state_and_events_but_fails_native_gate(
    baseline_010_results: dict[str, dict[str, Any]],
) -> None:
    result = baseline_010_results["compatibility-bridge"]
    assert result["hard_gates"]["behavior_parity"] is True
    assert result["hard_gates"]["database_parity"] is True
    assert result["hard_gates"]["side_effect_parity"] is True
    assert result["hard_gates"]["native_target"] is False
    assert result["fully_migrated"] is False
    evidence = result["scenarios"][0]["native"]
    assert "rest_framework" in evidence["forbidden_imports"]


def test_native_reference_passes_every_hard_gate(
    baseline_010_results: dict[str, dict[str, Any]],
) -> None:
    result = baseline_010_results["native-reference"]
    assert result["status"] == "passed"
    assert result["fully_migrated"] is True
    assert all(result["hard_gates"].values())
    assert result["metrics"]["scenario_count"] == 32
    assert result["errors"] == []
    for scenario in result["scenarios"]:
        evidence = scenario["native"]
        assert evidence["forbidden_imports"] == []
        assert evidence["settings_module"] == "target_settings"


def test_sanka_native_records_the_zero_readiness_outcome(
    baseline_010_results: dict[str, dict[str, Any]],
) -> None:
    """The pinned native plan supports neither the transaction-carrying
    viewset overrides nor the custom transition action, so apply emits nothing."""
    result = baseline_010_results["sanka-native"]
    assert result["candidate_id"] == "sanka-native"
    assert result["status"] == "failed"
    assert result["fully_migrated"] is False
    assert result["hard_gates"]["source_qualified"] is True
    assert result["hard_gates"]["regression_tests"] is True
    assert result["hard_gates"]["target_boot"] is False
    assert result["hard_gates"]["native_target"] is False
    assert result["metrics"]["behavioral_parity"]["passed"] == 0
    assert result["metrics"]["database_parity"]["passed"] == 0
    assert result["metrics"]["side_effect_parity"]["passed"] == 0
    assert result["metrics"]["native_compliance"]["passed"] == 0
