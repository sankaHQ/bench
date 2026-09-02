"""Unit coverage for the native verdict rule and the catch-all diagnostic."""

from __future__ import annotations

from sanka_bench.evaluator import _native_verdict, _scenario_reports, _served_by_catch_all
from sanka_bench.schema import validate_payload


def _evidence(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "app_is_fastapi": True,
        "route_class": "fastapi.routing.APIRoute",
        "route_is_apiroute": True,
        "route_path": "/api/items/",
        "endpoint_in_workspace": True,
        "forbidden_imports": [],
        "process_events": [],
        "socket_events": [],
        "settings_module": "svc.serving_settings",
    }
    base.update(overrides)
    return base


def test_apiroute_subclass_with_workspace_endpoint_is_compliant() -> None:
    compliant, detail = _native_verdict(
        {"native": _evidence(route_class="target_app.AnyMethodAPIRoute")}
    )
    assert compliant, detail


def test_raw_starlette_route_is_not_compliant() -> None:
    compliant, detail = _native_verdict(
        {"native": _evidence(route_class="starlette.routing.Route", route_is_apiroute=False)}
    )
    assert not compliant
    assert "served by starlette.routing.Route" in detail


def test_legacy_evidence_keeps_the_exact_class_rule() -> None:
    legacy = _evidence()
    legacy.pop("route_is_apiroute")
    legacy.pop("route_path")
    assert _native_verdict({"native": legacy})[0]
    legacy["route_class"] = "target_app.UniversalAPIRoute"
    compliant, detail = _native_verdict({"native": legacy})
    assert not compliant
    assert "target_app.UniversalAPIRoute" in detail


def test_catch_all_serving_a_non_404_is_flagged_but_a_404_is_not() -> None:
    evidence = _evidence(route_path="/{path:path}")
    assert _served_by_catch_all(evidence, {"response": {"status": 200}})
    assert not _served_by_catch_all(evidence, {"response": {"status": 404}})
    assert not _served_by_catch_all(
        _evidence(route_path="/api/items/{pk}/"), {"response": {"status": 200}}
    )
    assert not _served_by_catch_all(None, {"response": {"status": 200}})


def test_scenario_reports_carry_the_catch_all_diagnostic() -> None:
    source = {"response": {"status": 200, "body": {"ok": True}}, "database": {}, "side_effects": []}
    candidate = dict(source, native=_evidence(route_path="/{path:path}"))
    reports = _scenario_reports([{"id": "list"}], [[source]], [[candidate]])
    assert reports[0]["native_compliant"] is True
    assert reports[0]["catch_all_served"] is True


GATES = (
    "source_qualified",
    "regression_tests",
    "target_boot",
    "native_target",
    "behavior_parity",
    "database_parity",
    "side_effect_parity",
    "deterministic",
)
METRICS = (
    "route_coverage",
    "behavioral_parity",
    "database_parity",
    "side_effect_parity",
    "native_compliance",
)
DIGEST = "sha256:" + "0" * 64


def test_result_schema_accepts_the_new_optional_fields() -> None:
    result = {
        "schema_version": "sanka-bench/result/v0.2",
        "task_id": "drf-fastapi-001",
        "candidate_id": "x",
        "status": "passed",
        "fully_migrated": True,
        "hard_gates": dict.fromkeys(GATES, True),
        "metrics": {
            "scenario_count": 1,
            **{key: {"passed": 1, "total": 1, "rate": 1.0} for key in METRICS},
        },
        "scenarios": [
            {
                "id": "list",
                "target_ran": True,
                "behavior_match": True,
                "database_match": True,
                "side_effect_match": True,
                "native_compliant": True,
                "stable": True,
                "detail": "ok",
                "native": _evidence(),
            }
        ],
        "diagnostics": {
            "static_patterns": {"required_missing": [], "forbidden_present": []},
            "catch_all_served_scenarios": ["list"],
        },
        "provenance": {
            "task_digest": DIGEST,
            "source_digest": DIGEST,
            "candidate_digest": DIGEST,
            "evaluator_version": "0.0.3",
            "repeat": 2,
        },
        "errors": [],
    }
    validate_payload(result, "result", label="synthetic")
