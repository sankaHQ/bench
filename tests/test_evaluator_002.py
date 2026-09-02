from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sanka_bench.evaluator import evaluate_local
from sanka_bench.hashing import digest_tree
from sanka_bench.schema import load_and_validate


@pytest.fixture(scope="module")
def baseline_002_results(repository_root: Path, task_002_dir: Path) -> dict[str, dict[str, Any]]:
    return {
        name: evaluate_local(task_002_dir, repository_root / "baselines" / "drf-fastapi-002" / name)
        for name in ("noop", "compatibility-bridge", "native-reference", "sanka-native")
    }


def test_source_digest_is_pinned_to_fixture(task_002_dir: Path) -> None:
    task = load_and_validate(task_002_dir / "task.yaml", "task")
    assert task["source"]["provenance"]["digest"] == digest_tree(task_002_dir / "source")


def test_noop_fails_without_a_target(baseline_002_results: dict[str, dict[str, Any]]) -> None:
    result = baseline_002_results["noop"]
    assert result["status"] == "failed"
    assert result["hard_gates"]["source_qualified"] is True
    assert result["hard_gates"]["target_boot"] is False
    assert result["hard_gates"]["native_target"] is False


def test_bridge_preserves_auth_behavior_but_fails_native_gate(
    baseline_002_results: dict[str, dict[str, Any]],
) -> None:
    """The bridge inherits token auth and object permissions by dispatching
    into Django, so its behavior parity must hold across every 401/403
    scenario — and the gate must still reject it on serving evidence."""
    result = baseline_002_results["compatibility-bridge"]
    assert result["candidate_id"] == "sanka-compatibility-bridge"
    assert result["hard_gates"]["behavior_parity"] is True
    assert result["hard_gates"]["database_parity"] is True
    assert result["hard_gates"]["regression_tests"] is True
    assert result["hard_gates"]["native_target"] is False
    assert result["fully_migrated"] is False
    evidence = result["scenarios"][0]["native"]
    assert "rest_framework" in evidence["forbidden_imports"]


def test_native_reference_passes_every_hard_gate(
    baseline_002_results: dict[str, dict[str, Any]],
) -> None:
    result = baseline_002_results["native-reference"]
    assert result["status"] == "passed"
    assert result["fully_migrated"] is True
    assert all(result["hard_gates"].values())
    assert result["metrics"]["scenario_count"] == 13
    assert result["metrics"]["behavioral_parity"]["rate"] == 1.0
    assert result["metrics"]["native_compliance"]["rate"] == 1.0
    assert result["errors"] == []
    for scenario in result["scenarios"]:
        evidence = scenario["native"]
        assert evidence["forbidden_imports"] == []
        assert evidence["settings_module"] == "target_settings"
        assert evidence["route_class"] == "fastapi.routing.APIRoute"


def test_sanka_native_converter_passes_the_auth_fixture(
    baseline_002_results: dict[str, dict[str, Any]],
) -> None:
    """The converter's untouched output serves token auth without DRF."""
    result = baseline_002_results["sanka-native"]
    assert result["candidate_id"] == "sanka-native"
    assert result["status"] == "passed"
    assert result["fully_migrated"] is True
    assert all(result["hard_gates"].values())
    assert result["errors"] == []
    for scenario in result["scenarios"]:
        evidence = scenario["native"]
        assert evidence["forbidden_imports"] == []
        assert evidence["settings_module"] == "sanka_settings"


def test_auth_scenarios_are_present_and_distinct(task_002_dir: Path) -> None:
    import json

    scenarios = json.loads(
        (task_002_dir / "public-tests" / "scenarios.json").read_text(encoding="utf-8")
    )
    ids = {scenario["id"] for scenario in scenarios}
    assert {
        "list-unauthenticated",
        "list-invalid-token",
        "list-malformed-header",
        "create-unauthenticated",
        "patch-other-author",
        "delete-other-author",
    } <= ids
