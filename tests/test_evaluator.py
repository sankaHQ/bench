from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sanka_bench.evaluator import evaluate_local
from sanka_bench.hashing import digest_tree
from sanka_bench.schema import load_and_validate


@pytest.fixture(scope="module")
def baseline_results(repository_root: Path, task_dir: Path) -> dict[str, dict[str, Any]]:
    return {
        name: evaluate_local(task_dir, repository_root / "baselines" / "drf-fastapi-001" / name)
        for name in ("noop", "compatibility-bridge", "native-reference", "sanka-native")
    }


def test_source_digest_is_pinned_to_fixture(task_dir: Path) -> None:
    task = load_and_validate(task_dir / "task.yaml", "task")
    assert task["source"]["provenance"]["digest"] == digest_tree(task_dir / "source")


def test_noop_fails_without_a_target(baseline_results: dict[str, dict[str, Any]]) -> None:
    result = baseline_results["noop"]
    assert result["status"] == "failed"
    assert result["fully_migrated"] is False
    assert result["hard_gates"]["source_qualified"] is True
    assert result["hard_gates"]["regression_tests"] is True
    assert result["hard_gates"]["target_boot"] is False
    assert result["hard_gates"]["native_target"] is False
    assert any("missing target entrypoint" in error for error in result["errors"])


def test_pr13_bridge_preserves_behavior_but_fails_native_gate(
    baseline_results: dict[str, dict[str, Any]],
) -> None:
    result = baseline_results["compatibility-bridge"]
    assert result["candidate_id"] == "sanka-pr13-compatibility-bridge"
    assert result["fully_migrated"] is False
    assert result["hard_gates"]["target_boot"] is True
    assert result["hard_gates"]["behavior_parity"] is True
    assert result["hard_gates"]["database_parity"] is True
    assert result["hard_gates"]["native_target"] is False
    # The gate fails on recorded serving evidence, not on source text.
    assert any("forbidden serving imports" in error for error in result["errors"])
    evidence = result["scenarios"][0]["native"]
    assert "rest_framework" in evidence["forbidden_imports"]
    assert "django.core.asgi" in evidence["forbidden_imports"]
    # The static scan still surfaces the same story as a diagnostic.
    findings = result["diagnostics"]["static_patterns"]["forbidden_present"]
    assert {"file": "target_app.py", "pattern": "get_asgi_application"} in findings


def test_native_reference_passes_every_hard_gate(
    baseline_results: dict[str, dict[str, Any]],
) -> None:
    result = baseline_results["native-reference"]
    assert result["status"] == "passed"
    assert result["fully_migrated"] is True
    assert all(result["hard_gates"].values())
    assert result["metrics"]["behavioral_parity"] == {"passed": 5, "total": 5, "rate": 1.0}
    assert result["metrics"]["database_parity"] == {"passed": 5, "total": 5, "rate": 1.0}
    assert result["metrics"]["native_compliance"] == {"passed": 5, "total": 5, "rate": 1.0}
    assert result["errors"] == []
    for scenario in result["scenarios"]:
        evidence = scenario["native"]
        assert evidence["app_is_fastapi"] is True
        assert evidence["route_class"] == "fastapi.routing.APIRoute"
        assert evidence["endpoint_in_workspace"] is True
        assert evidence["forbidden_imports"] == []
        assert evidence["process_events"] == []
        assert evidence["socket_events"] == []
        assert evidence["settings_module"] == "target_settings"
    assert result["diagnostics"]["static_patterns"]["required_missing"] == []


def test_sanka_native_converter_passes_every_hard_gate(
    baseline_results: dict[str, dict[str, Any]],
) -> None:
    """The product milestone: Sanka's own generated output, unedited."""
    result = baseline_results["sanka-native"]
    assert result["candidate_id"] == "sanka-native"
    assert result["status"] == "passed"
    assert result["fully_migrated"] is True
    assert all(result["hard_gates"].values())
    assert result["errors"] == []
    for scenario in result["scenarios"]:
        evidence = scenario["native"]
        assert evidence["forbidden_imports"] == []
        assert evidence["route_class"] == "fastapi.routing.APIRoute"
        assert evidence["settings_module"] == "sanka_settings"


def test_obfuscated_bridge_fails_on_runtime_evidence_despite_clean_entrypoint(
    repository_root: Path,
    task_dir: Path,
) -> None:
    """A facade that hides DRF dispatch in an imported helper.

    The entrypoint contains none of the forbidden text patterns, so the
    retired single-file string gate would have accepted it. The recorded
    serving evidence must reject it anyway.
    """
    result = evaluate_local(
        task_dir,
        repository_root / "tests" / "fixtures" / "obfuscated-bridge",
    )
    static = result["diagnostics"]["static_patterns"]
    entry_findings = [
        finding for finding in static["forbidden_present"] if finding["file"] == "target_app.py"
    ]
    assert entry_findings == []
    assert static["required_missing"] == []
    assert result["hard_gates"]["target_boot"] is True
    assert result["hard_gates"]["behavior_parity"] is True
    assert result["hard_gates"]["native_target"] is False
    assert result["fully_migrated"] is False
    assert any("forbidden serving imports" in error for error in result["errors"])
    evidence = result["scenarios"][0]["native"]
    assert "rest_framework" in evidence["forbidden_imports"]
    assert "django.core.asgi" in evidence["forbidden_imports"]
