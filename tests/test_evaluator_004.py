from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sanka_bench.evaluator import evaluate_local
from sanka_bench.hashing import digest_tree
from sanka_bench.schema import load_and_validate


@pytest.fixture(scope="session")
def task_004_dir(repository_root: Path) -> Path:
    return repository_root / "tasks" / "drf-fastapi" / "drf-fastapi-004"


@pytest.fixture(scope="module")
def baseline_004_results(repository_root: Path, task_004_dir: Path) -> dict[str, dict[str, Any]]:
    return {
        name: evaluate_local(task_004_dir, repository_root / "baselines" / "drf-fastapi-004" / name)
        for name in ("noop", "compatibility-bridge", "native-reference", "sanka-native")
    }


def test_source_digest_is_pinned_to_fixture(task_004_dir: Path) -> None:
    task = load_and_validate(task_004_dir / "task.yaml", "task")
    assert task["source"]["provenance"]["digest"] == digest_tree(task_004_dir / "source")


def test_public_scenarios_are_a_strict_subset_of_the_graded_set(task_004_dir: Path) -> None:
    """The saturation-breaking contract: candidates see 5 scenarios, the
    evaluator grades a superset whose hidden members exercise the signal
    side effects the visible surface deliberately under-specifies."""
    public = json.loads(
        (task_004_dir / "public-tests" / "scenarios.json").read_text(encoding="utf-8")
    )
    graded = json.loads(
        (task_004_dir / "evaluation" / "scenarios.json").read_text(encoding="utf-8")
    )
    public_ids = [scenario["id"] for scenario in public]
    graded_ids = [scenario["id"] for scenario in graded]
    assert len(public_ids) == 5
    assert len(graded_ids) == 17
    assert set(public_ids) < set(graded_ids)
    assert {
        "create-account-balance-ignored",
        "rapid-entry-creates-compose",
        "delete-entry-reverses-balance",
        "transfer-insufficient-funds-rolls-back",
        "transfer-audit-trail",
        "delete-account-cascade-audit",
        "audit-after-mixed-chain",
    } <= set(graded_ids) - set(public_ids)
    task = load_and_validate(task_004_dir / "task.yaml", "task")
    assert task["evaluation"]["scenarios"] == "evaluation/scenarios.json"


def test_noop_fails_without_a_target(baseline_004_results: dict[str, dict[str, Any]]) -> None:
    result = baseline_004_results["noop"]
    assert result["status"] == "failed"
    assert result["hard_gates"]["source_qualified"] is True
    assert result["hard_gates"]["target_boot"] is False
    assert result["hard_gates"]["native_target"] is False


def test_bridge_preserves_signal_behavior_but_fails_native_gate(
    baseline_004_results: dict[str, dict[str, Any]],
) -> None:
    """The proxied Django application carries the signals with it, so the
    bridge reproduces balances and the audit trail exactly — and still
    fails on recorded serving evidence."""
    result = baseline_004_results["compatibility-bridge"]
    assert result["hard_gates"]["behavior_parity"] is True
    assert result["hard_gates"]["database_parity"] is True
    assert result["hard_gates"]["native_target"] is False
    assert result["fully_migrated"] is False
    evidence = result["scenarios"][0]["native"]
    assert "rest_framework" in evidence["forbidden_imports"]


def test_native_reference_passes_every_hard_gate(
    baseline_004_results: dict[str, dict[str, Any]],
) -> None:
    """The reference serves with the source signal receivers never
    connected and reapplies every side effect explicitly."""
    result = baseline_004_results["native-reference"]
    assert result["status"] == "passed"
    assert result["fully_migrated"] is True
    assert all(result["hard_gates"].values())
    assert result["metrics"]["scenario_count"] == 17
    assert result["errors"] == []
    for scenario in result["scenarios"]:
        evidence = scenario["native"]
        assert evidence["forbidden_imports"] == []
        assert evidence["settings_module"] == "target_settings"


def test_sanka_native_converter_fails_the_signal_fixture_honestly(
    baseline_004_results: dict[str, dict[str, Any]],
) -> None:
    """The frozen converter output is the honest envelope record:
    mixin-composed viewsets and the transfer custom action are outside the
    native plan today, so only the plain-account surface passes."""
    result = baseline_004_results["sanka-native"]
    assert result["candidate_id"] == "sanka-native"
    assert result["status"] == "failed"
    assert result["fully_migrated"] is False
    assert result["hard_gates"]["behavior_parity"] is False
    assert result["hard_gates"]["database_parity"] is False
    assert result["hard_gates"]["native_target"] is True
    assert result["metrics"]["behavioral_parity"]["passed"] == 5
    assert result["metrics"]["database_parity"]["passed"] == 10
    assert result["metrics"]["native_compliance"]["passed"] == 17
    passing = {
        scenario["id"]
        for scenario in result["scenarios"]
        if scenario["behavior_match"] and scenario["database_match"]
    }
    assert passing == {
        "list-accounts",
        "retrieve-account",
        "create-account",
        "create-account-balance-ignored",
        "patch-account-balance-ignored",
    }
