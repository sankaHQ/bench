"""Qualified baseline controls for the eleven DRF-to-FastAPI tasks.

These are the cases that used to live in eleven per-task copies
(``test_evaluator.py`` and ``test_evaluator_002.py`` ... ``test_evaluator_011.py``).
Every case id starts with its task, so ``make test-evaluator-008`` still runs one
task with ``-k drf-fastapi-008``; where a copy named a case differently, the id
keeps that name.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from sanka_bench.evaluator import evaluate_local
from sanka_bench.hashing import digest_tree
from sanka_bench.schema import load_and_validate

TASKS = tuple(f"{number:03d}" for number in range(1, 12))
CANDIDATES = ("noop", "compatibility-bridge", "native-reference", "sanka-native")
API_ROUTE = "fastapi.routing.APIRoute"
Baselines = Callable[[str], dict[str, dict[str, Any]]]


def task_dir(root: Path, number: str) -> Path:
    return root / "tasks" / "drf-fastapi" / f"drf-fastapi-{number}"


def cases(numbers: Any) -> list[Any]:
    """One case per task; a mapping value becomes the case name after the task id."""
    if isinstance(numbers, dict):
        return [
            pytest.param(number, id=f"drf-fastapi-{number}-{name}")
            for number, name in numbers.items()
        ]
    return [pytest.param(number, id=f"drf-fastapi-{number}") for number in numbers]


@pytest.fixture(scope="module")
def baselines(repository_root: Path) -> Baselines:
    """Evaluate a task's four frozen baselines once, on first use in this module."""
    evaluated: dict[str, dict[str, dict[str, Any]]] = {}

    def results(number: str) -> dict[str, dict[str, Any]]:
        if number not in evaluated:
            evaluated[number] = {
                name: evaluate_local(
                    task_dir(repository_root, number),
                    repository_root / "baselines" / f"drf-fastapi-{number}" / name,
                )
                for name in CANDIDATES
            }
        return evaluated[number]

    return results


def scenario_ids(task: Path, split: str) -> list[str]:
    scenarios = json.loads((task / split / "scenarios.json").read_text(encoding="utf-8"))
    return [scenario["id"] for scenario in scenarios]


@pytest.mark.parametrize("number", cases(TASKS))
def test_source_digest_is_pinned_to_fixture(repository_root: Path, number: str) -> None:
    task = task_dir(repository_root, number)
    loaded = load_and_validate(task / "task.yaml", "task")
    assert loaded["source"]["provenance"]["digest"] == digest_tree(task / "source")


# Public count, graded count, whether the public scenarios open the graded file,
# and hidden scenarios that must stay out of the public set.
GRADED: dict[str, tuple[int, int, bool, set[str]]] = {
    # Candidates see 5 scenarios; the hidden members exercise the signal side
    # effects the visible surface deliberately under-specifies.
    "004": (
        5,
        17,
        False,
        {
            "create-account-balance-ignored",
            "rapid-entry-creates-compose",
            "delete-entry-reverses-balance",
            "transfer-insufficient-funds-rolls-back",
            "transfer-audit-trail",
            "delete-account-cascade-audit",
            "audit-after-mixed-chain",
        },
    ),
    # The public seven show each main capability; the hidden matrix pins
    # authentication/permission ordering and the exact 401/403/404 branches.
    "005": (
        7,
        31,
        False,
        {
            "list-invalid-token-beats-session",
            "create-session-missing-csrf",
            "create-expired-token-beats-session",
            "retrieve-missing-anonymous",
            "retrieve-missing-authenticated",
            "patch-other-owner",
            "destroy-owner-nonstaff",
            "destroy-staff-session",
            "review-owner-nonstaff",
            "review-staff-session",
        },
    ),
    # The visible cases establish the graph shape; hidden cases pin depth-two
    # error indexes, replacement semantics, and rollback at later children.
    "006": (
        7,
        32,
        True,
        {
            "create-invalid-second-item-second-adjustment",
            "create-duplicate-item-sku-rolls-back",
            "create-duplicate-adjustment-in-second-item-rolls-back",
            "put-duplicate-adjustment-in-second-item-rolls-back",
            "patch-reference-only-preserves-graph",
            "patch-empty-items-clears-graph",
            "patch-missing-nested-field-rejected",
            "patch-duplicate-adjustment-rolls-back",
        },
    ),
    # The public six establish the representation surface; hidden cases pin
    # cursor stability, tie direction, conditional branches, and query envelopes.
    "007": (
        6,
        30,
        True,
        {
            "walk-default-third-page",
            "cursor-stable-after-newer-insert",
            "ordered-cursor-stable-after-middle-insert",
            "ordering-posted-at-breaks-ties-by-id",
            "search-empty-result-envelope",
            "conditional-etag-wildcard",
            "stale-etag-after-patch-returns-new-body",
            "current-etag-after-patch-returns-304",
            "malformed-cursor-has-exact-error",
        },
    ),
    # The public eight show canonical parity; hidden cases carry alternate
    # slash forms, the second regex code, cross-style mutations, and rollback.
    "008": (
        8,
        32,
        True,
        {
            "function-list-no-slash-is-also-canonical",
            "class-list-slash-redirects-back",
            "viewset-list-no-slash-redirects-forward",
            "function-detail-at-and-dot-code",
            "cross-create-function-read-class",
            "cross-patch-class-read-viewset",
            "cross-delete-viewset-read-class",
            "viewset-full-update-missing-code-rolls-back",
        },
    ),
    # The public eight expose the basic file surface; hidden cases carry
    # boundary quirks, suffix mutations, byte limits, rollback, and file state.
    "009": (
        8,
        32,
        True,
        {
            "upload-api-unusual-boundary",
            "upload-json-csv",
            "upload-exactly-32-bytes",
            "upload-33-bytes-api",
            "upload-boundary-like-content",
            "upload-then-download-binary",
            "valid-upload-then-rejected-upload-rolls-back-files",
            "duplicate-after-valid-upload-keeps-original-file",
        },
    ),
    # The public seven expose basic locking; hidden cases exhaust the full
    # state-transition matrix plus invalid-target and stale-transition rollback.
    "010": (
        7,
        32,
        True,
        {
            "transition-draft-to-cancelled",
            "transition-submitted-to-approved",
            "transition-submitted-to-cancelled",
            "transition-approved-to-shipped",
            "transition-shipped-to-cancelled",
            "transition-cancelled-to-draft",
            "unknown-transition-target-validation",
            "stale-transition-rolls-back-both-tables",
        },
    ),
    # The public seven expose aggregate basics; hidden cases carry ordering,
    # pagination, mutation chains, decimal boundaries, and empty datasets.
    "011": (
        7,
        32,
        True,
        {
            "order-posted-total-ascending-page-two",
            "two-creates-use-latest-related-row",
            "patch-moves-transaction-across-pages",
            "duplicate-create-leaves-aggregates-unchanged",
            "fully-empty-summary",
            "fully-empty-account-page",
        },
    ),
}


@pytest.mark.parametrize("number", cases(tuple(GRADED)))
def test_public_scenarios_are_a_strict_subset_of_the_graded_set(
    repository_root: Path, number: str
) -> None:
    public_count, graded_count, public_first, hidden = GRADED[number]
    task = task_dir(repository_root, number)
    public_ids = scenario_ids(task, "public-tests")
    graded_ids = scenario_ids(task, "evaluation")
    assert len(public_ids) == public_count
    assert len(graded_ids) == graded_count
    if public_first:
        public = json.loads((task / "public-tests/scenarios.json").read_text(encoding="utf-8"))
        graded = json.loads((task / "evaluation/scenarios.json").read_text(encoding="utf-8"))
        assert public == graded[: len(public)]
    assert set(public_ids) < set(graded_ids)
    assert hidden <= set(graded_ids) - set(public_ids)
    loaded = load_and_validate(task / "task.yaml", "task")
    assert loaded["evaluation"]["scenarios"] == "evaluation/scenarios.json"


# Public scenarios that carry the task's contract.
PUBLIC_CONTRACT = {
    "002": (
        "auth_scenarios_are_present_and_distinct",
        {
            "list-unauthenticated",
            "list-invalid-token",
            "list-malformed-header",
            "create-unauthenticated",
            "patch-other-author",
            "delete-other-author",
        },
    ),
    # The rollback contract is observable: the scenario exists and the fixture's
    # own test suite pins that a failed business rule leaves no partial rows, so a
    # non-atomic candidate fails database parity.
    "003": (
        "rollback_scenario_compares_database_state",
        {
            "create-rollback-on-business-rule",
            "create-nested-item-invalid",
            "create-duplicate-reference",
            "create-price-too-many-decimals",
            "create-items-not-a-list",
        },
    ),
}


@pytest.mark.parametrize(
    "number", cases({number: name for number, (name, _) in PUBLIC_CONTRACT.items()})
)
def test_public_scenarios_carry_the_task_contract(repository_root: Path, number: str) -> None:
    _, required = PUBLIC_CONTRACT[number]
    assert required <= set(scenario_ids(task_dir(repository_root, number), "public-tests"))


@pytest.mark.parametrize("number", cases(TASKS))
def test_noop_fails_without_a_target(baselines: Baselines, number: str) -> None:
    result = baselines(number)["noop"]
    assert result["status"] == "failed"
    assert result["hard_gates"]["source_qualified"] is True
    if number != "003":
        assert result["hard_gates"]["target_boot"] is False
    assert result["hard_gates"]["native_target"] is False
    if number == "001":
        assert result["fully_migrated"] is False
        assert result["hard_gates"]["regression_tests"] is True
        assert any("missing target entrypoint" in error for error in result["errors"])


BRIDGE = {
    "001": "pr13_bridge_preserves_behavior_but_fails_native_gate",
    # The bridge inherits token auth and object permissions by dispatching into
    # Django, so its behavior parity must hold across every 401/403 scenario.
    "002": "bridge_preserves_auth_behavior_but_fails_native_gate",
    "003": "bridge_preserves_nested_behavior_but_fails_native_gate",
    # The proxied Django application carries the signals with it, so the bridge
    # reproduces balances and the audit trail exactly.
    "004": "bridge_preserves_signal_behavior_but_fails_native_gate",
    "005": "bridge_preserves_the_full_matrix_but_fails_native_gate",
    "006": "bridge_preserves_graph_behavior_but_fails_native_gate",
    "007": "bridge_preserves_response_shapes_but_fails_native_gate",
    "008": "bridge_preserves_mixed_style_behavior_but_fails_native_gate",
    "009": "bridge_preserves_files_and_negotiation_but_fails_native_gate",
    "010": "bridge_preserves_state_and_events_but_fails_native_gate",
    "011": "bridge_preserves_aggregates_and_mutations_but_fails_native_gate",
}
BRIDGE_CANDIDATE_IDS = {
    "001": "sanka-pr13-compatibility-bridge",
    "002": "sanka-compatibility-bridge",
}
SIDE_EFFECT_TASKS = {"006", "007", "008", "009", "010", "011"}


@pytest.mark.parametrize("number", cases(BRIDGE))
def test_bridge_preserves_behavior_but_fails_native_gate(baselines: Baselines, number: str) -> None:
    """Every bridge reproduces the source, and the gate still rejects it on serving evidence."""
    result = baselines(number)["compatibility-bridge"]
    if number in BRIDGE_CANDIDATE_IDS:
        assert result["candidate_id"] == BRIDGE_CANDIDATE_IDS[number]
    assert result["fully_migrated"] is False
    assert result["hard_gates"]["behavior_parity"] is True
    assert result["hard_gates"]["database_parity"] is True
    if number in SIDE_EFFECT_TASKS:
        assert result["hard_gates"]["side_effect_parity"] is True
    if number == "002":
        assert result["hard_gates"]["regression_tests"] is True
    assert result["hard_gates"]["native_target"] is False
    evidence = result["scenarios"][0]["native"]
    assert "rest_framework" in evidence["forbidden_imports"]
    if number == "001":
        assert result["hard_gates"]["target_boot"] is True
        # The gate fails on recorded serving evidence, not on source text.
        assert any("forbidden serving imports" in error for error in result["errors"])
        assert "django.core.asgi" in evidence["forbidden_imports"]
        # The static scan still surfaces the same story as a diagnostic.
        findings = result["diagnostics"]["static_patterns"]["forbidden_present"]
        assert {"file": "target_app.py", "pattern": "get_asgi_application"} in findings


NATIVE_SCENARIO_COUNTS = {
    "002": 13,
    "003": 16,
    "004": 17,
    "005": 31,
    "006": 32,
    "007": 30,
    "008": 32,
    "009": 32,
    "010": 32,
    "011": 32,
}


@pytest.mark.parametrize("number", cases(TASKS))
def test_native_reference_passes_every_hard_gate(baselines: Baselines, number: str) -> None:
    result = baselines(number)["native-reference"]
    assert result["status"] == "passed"
    assert result["fully_migrated"] is True
    assert all(result["hard_gates"].values())
    if number == "001":
        complete = {"passed": 5, "total": 5, "rate": 1.0}
        assert result["metrics"]["behavioral_parity"] == complete
        assert result["metrics"]["database_parity"] == complete
        assert result["metrics"]["native_compliance"] == complete
    else:
        assert result["metrics"]["scenario_count"] == NATIVE_SCENARIO_COUNTS[number]
    if number == "002":
        assert result["metrics"]["behavioral_parity"]["rate"] == 1.0
        assert result["metrics"]["native_compliance"]["rate"] == 1.0
    assert result["errors"] == []
    if number == "003":
        return
    for scenario in result["scenarios"]:
        evidence = scenario["native"]
        assert evidence["forbidden_imports"] == []
        assert evidence["settings_module"] == "target_settings"
        if number in {"001", "002"}:
            assert evidence["route_class"] == API_ROUTE
        if number == "001":
            assert evidence["app_is_fastapi"] is True
            assert evidence["endpoint_in_workspace"] is True
            assert evidence["process_events"] == []
            assert evidence["socket_events"] == []
    if number == "001":
        assert result["diagnostics"]["static_patterns"]["required_missing"] == []


@pytest.mark.parametrize(
    "number",
    cases(
        {
            # The product milestone: Sanka's own generated output, unedited.
            "001": "sanka_native_converter_passes_every_hard_gate",
            # The converter's untouched output serves token auth without DRF.
            "002": "sanka_native_converter_passes_the_auth_fixture",
            # The author's create() carried over verbatim: transaction boundary,
            # business rule, rollback and all.
            "003": "sanka_native_converter_passes_the_nested_fixture",
        }
    ),
)
def test_sanka_native_converter_passes(baselines: Baselines, number: str) -> None:
    result = baselines(number)["sanka-native"]
    assert result["candidate_id"] == "sanka-native"
    assert result["status"] == "passed"
    assert result["fully_migrated"] is True
    assert all(result["hard_gates"].values())
    assert result["errors"] == []
    for scenario in result["scenarios"]:
        evidence = scenario["native"]
        assert evidence["forbidden_imports"] == []
        if number == "001":
            assert evidence["route_class"] == API_ROUTE
        assert evidence["settings_module"] == "sanka_settings"


@pytest.mark.parametrize("number", cases(["004"]))
def test_sanka_native_converter_fails_the_signal_fixture_honestly(
    baselines: Baselines, number: str
) -> None:
    """The frozen converter output is the honest envelope record: mixin-composed
    viewsets and the transfer custom action are outside the native plan today, so
    only the plain-account surface passes."""
    result = baselines(number)["sanka-native"]
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


# 005: the permission matrix leaves readiness below the default threshold.
# 006: only the API root is generatable.
# 007: the source viewset overrides leave only the API root generatable.
# 008: mixed legacy view kinds leave readiness below the default threshold.
@pytest.mark.parametrize("number", cases(["005", "006", "007", "008"]))
def test_sanka_native_records_the_readiness_abstention(baselines: Baselines, number: str) -> None:
    """Readiness stays below the default threshold, so apply emits a gap report
    instead of an overlay."""
    result = baselines(number)["sanka-native"]
    assert result["candidate_id"] == "sanka-native"
    assert result["status"] == "failed"
    assert result["fully_migrated"] is False
    assert result["hard_gates"]["source_qualified"] is True
    assert result["hard_gates"]["regression_tests"] is True
    assert result["hard_gates"]["target_boot"] is False
    assert result["hard_gates"]["behavior_parity"] is False
    assert result["hard_gates"]["database_parity"] is False
    assert result["hard_gates"]["native_target"] is False
    if number == "005":
        assert result["metrics"]["route_coverage"]["passed"] == 0
    else:
        assert result["metrics"]["behavioral_parity"]["passed"] == 0
        assert result["metrics"]["database_parity"]["passed"] == 0
        assert result["metrics"]["native_compliance"]["passed"] == 0


# 009: neither serializer-driven multipart routes nor the custom download action.
# 010: neither the transaction-carrying viewset overrides nor the transition action.
# 011: neither the two non-viewset aggregate surfaces nor the slug-related serializer.
@pytest.mark.parametrize("number", cases(["009", "010", "011"]))
def test_sanka_native_records_the_zero_readiness_outcome(baselines: Baselines, number: str) -> None:
    """The pinned native plan supports none of the task's surfaces, so apply
    honestly emits nothing."""
    result = baselines(number)["sanka-native"]
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


@pytest.mark.parametrize("number", cases(["001"]))
def test_obfuscated_bridge_fails_on_runtime_evidence_despite_clean_entrypoint(
    repository_root: Path, number: str
) -> None:
    """A facade that hides DRF dispatch in an imported helper.

    The entrypoint contains none of the forbidden text patterns, so the
    retired single-file string gate would have accepted it. The recorded
    serving evidence must reject it anyway.
    """
    result = evaluate_local(
        task_dir(repository_root, number),
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
