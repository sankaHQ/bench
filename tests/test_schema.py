from __future__ import annotations

from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from sanka_bench.schema import SchemaError, load_and_validate, load_schema, validate_payload


def test_all_versioned_schemas_are_valid() -> None:
    for name in ("task", "candidate", "result"):
        assert load_schema(name)["$schema"].endswith("2020-12/schema")


def test_checked_in_task_and_candidates_validate(repository_root: Path, task_dir: Path) -> None:
    assert load_and_validate(task_dir / "task.yaml", "task")["id"] == "drf-fastapi-001"
    for path in sorted((repository_root / "baselines").glob("*/*/candidate.yaml")):
        load_and_validate(path, "candidate")


def test_candidate_v02_accepts_and_validates_stats() -> None:
    payload = {
        "schema_version": "sanka-bench/candidate/v0.2",
        "id": "agent-run",
        "kind": "overlay",
        "overlay": "overlay",
        "provenance": {"producer": "claude-code", "revision": "model", "command": ""},
        "stats": {"turns": 36, "duration_seconds": 411.5, "cost_usd": 1.23},
    }
    validate_payload(payload, "candidate", label="candidate")
    payload["stats"] = {"turns": -1}
    with pytest.raises(SchemaError):
        validate_payload(payload, "candidate", label="candidate")


def test_candidate_and_result_stats_accept_claude_usage_and_nullable_cost() -> None:
    stats = {
        "turns": 3,
        "duration_seconds": 1.3,
        "setup_seconds": 0.2,
        "evaluation_seconds": 0.4,
        "end_to_end_seconds": 1.9,
        "requested_model_id": "claude-sonnet-5",
        "actual_model_id": "claude-sonnet-5-20260901",
        "billing_mode": "subscription",
        "input_tokens": 100,
        "cache_creation_input_tokens": 20,
        "cache_read_input_tokens": 40,
        "output_tokens": 30,
        "total_tokens": 190,
        "cost_usd": None,
        "reported_equivalent_cost_usd": 1.25,
        "cost_basis": "subscription-no-marginal-cost",
    }

    for name in ("candidate", "result"):
        schema = load_schema(name)["$defs"]["agentStats"]
        assert not list(Draft202012Validator(schema).iter_errors(stats))


def test_overlay_candidate_requires_overlay_path() -> None:
    payload = {
        "schema_version": "sanka-bench/candidate/v0.1",
        "id": "missing-overlay",
        "kind": "overlay",
        "provenance": {"producer": "test", "revision": "1", "command": ""},
    }
    with pytest.raises(SchemaError, match="overlay"):
        validate_payload(payload, "candidate", label="candidate")
