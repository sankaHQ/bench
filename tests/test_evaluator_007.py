from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sanka_bench.evaluator import evaluate_local
from sanka_bench.hashing import digest_tree
from sanka_bench.schema import load_and_validate


@pytest.fixture(scope="session")
def task_007_dir(repository_root: Path) -> Path:
    return repository_root / "tasks" / "drf-fastapi" / "drf-fastapi-007"


@pytest.fixture(scope="module")
def baseline_007_results(repository_root: Path, task_007_dir: Path) -> dict[str, dict[str, Any]]:
    return {
        name: evaluate_local(task_007_dir, repository_root / "baselines" / "drf-fastapi-007" / name)
        for name in ("noop", "compatibility-bridge", "native-reference", "sanka-native")
    }


def test_source_digest_is_pinned_to_fixture(task_007_dir: Path) -> None:
    task = load_and_validate(task_007_dir / "task.yaml", "task")
    assert task["source"]["provenance"]["digest"] == digest_tree(task_007_dir / "source")


def test_public_scenarios_are_a_strict_subset_of_the_graded_set(task_007_dir: Path) -> None:
    """The public six establish the representation surface; hidden cases pin
    cursor stability, tie direction, conditional branches, and query envelopes."""
    public = json.loads(
        (task_007_dir / "public-tests" / "scenarios.json").read_text(encoding="utf-8")
    )
    graded = json.loads(
        (task_007_dir / "evaluation" / "scenarios.json").read_text(encoding="utf-8")
    )
    public_ids = [scenario["id"] for scenario in public]
    graded_ids = [scenario["id"] for scenario in graded]
    assert len(public_ids) == 6
    assert len(graded_ids) == 30
    assert public == graded[: len(public)]
    assert set(public_ids) < set(graded_ids)
    assert {
        "walk-default-third-page",
        "cursor-stable-after-newer-insert",
        "ordered-cursor-stable-after-middle-insert",
        "ordering-posted-at-breaks-ties-by-id",
        "search-empty-result-envelope",
        "conditional-etag-wildcard",
        "stale-etag-after-patch-returns-new-body",
        "current-etag-after-patch-returns-304",
        "malformed-cursor-has-exact-error",
    } <= set(graded_ids) - set(public_ids)
    task = load_and_validate(task_007_dir / "task.yaml", "task")
    assert task["evaluation"]["scenarios"] == "evaluation/scenarios.json"


def test_noop_fails_without_a_target(baseline_007_results: dict[str, dict[str, Any]]) -> None:
    result = baseline_007_results["noop"]
    assert result["status"] == "failed"
    assert result["hard_gates"]["source_qualified"] is True
    assert result["hard_gates"]["target_boot"] is False
    assert result["hard_gates"]["native_target"] is False


def test_bridge_preserves_response_shapes_but_fails_native_gate(
    baseline_007_results: dict[str, dict[str, Any]],
) -> None:
    result = baseline_007_results["compatibility-bridge"]
    assert result["hard_gates"]["behavior_parity"] is True
    assert result["hard_gates"]["database_parity"] is True
    assert result["hard_gates"]["side_effect_parity"] is True
    assert result["hard_gates"]["native_target"] is False
    assert result["fully_migrated"] is False
    evidence = result["scenarios"][0]["native"]
    assert "rest_framework" in evidence["forbidden_imports"]


def test_native_reference_passes_every_hard_gate(
    baseline_007_results: dict[str, dict[str, Any]],
) -> None:
    result = baseline_007_results["native-reference"]
    assert result["status"] == "passed"
    assert result["fully_migrated"] is True
    assert all(result["hard_gates"].values())
    assert result["metrics"]["scenario_count"] == 30
    assert result["errors"] == []
    for scenario in result["scenarios"]:
        evidence = scenario["native"]
        assert evidence["forbidden_imports"] == []
        assert evidence["settings_module"] == "target_settings"


def test_sanka_native_records_the_readiness_abstention(
    baseline_007_results: dict[str, dict[str, Any]],
) -> None:
    """The source viewset overrides leave only the API root generatable and
    readiness below threshold, so apply emits a gap report instead of an overlay."""
    result = baseline_007_results["sanka-native"]
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
