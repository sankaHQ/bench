from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sanka_bench.report import collect, family_key, render_html, render_svg, sample_index

GATES = {
    "source_qualified": True,
    "regression_tests": True,
    "target_boot": True,
    "native_target": True,
    "behavior_parity": True,
    "database_parity": True,
    "side_effect_parity": True,
    "deterministic": True,
}


def _write(reports: Path, task: str, candidate: str, *, migrated: bool, cost: float) -> None:
    payload: dict[str, Any] = {
        "task_id": task,
        "candidate_id": candidate,
        "fully_migrated": migrated,
        "hard_gates": {**GATES, "behavior_parity": migrated},
        "provenance": {
            "evaluator_version": "0.0.3",
            "candidate_stats": {"turns": 30, "duration_seconds": 120.0, "cost_usd": cost},
        },
    }
    (reports / f"{task}-{candidate}.json").write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture
def sampled_reports(tmp_path: Path) -> Path:
    reports = tmp_path / "reports"
    reports.mkdir()
    # task A: 3/3 samples pass; task B: 1/3; task C: 0/3 — all for one approach
    for sample, migrated in ((1, True), (2, True), (3, True)):
        _write(reports, "task-a", f"codex-luna-with-sanka-s{sample}", migrated=migrated, cost=1.0)
    for sample, migrated in ((1, True), (2, False), (3, False)):
        _write(reports, "task-b", f"codex-luna-with-sanka-s{sample}", migrated=migrated, cost=2.0)
    for sample in (1, 2, 3):
        _write(reports, "task-c", f"codex-luna-with-sanka-s{sample}", migrated=False, cost=3.0)
    return reports


def test_sample_suffixes_fold_into_one_family() -> None:
    assert family_key("codex-luna-with-sanka-s2") == "codex-luna-with-sanka"
    assert family_key("codex-luna-with-sanka") == "codex-luna-with-sanka"
    assert sample_index("codex-luna-with-sanka-s3") == 3
    assert sample_index("codex-luna-with-sanka") == 1
    assert family_key("sanka-pr13-compatibility-bridge-s2") == "compatibility-bridge"


def test_rows_aggregate_task_samples_with_intervals(sampled_reports: Path) -> None:
    data = collect(sampled_reports, {"task-a": 10, "task-b": 20, "task-c": 30})
    assert data["samples"] == 3
    (row,) = data["rows"]
    assert row["covered"] == ["task-a", "task-b", "task-c"]
    # a task counts as migrated only when every sample passed
    assert row["migrated"] == ["task-a"]
    assert row["outcomes"]["task-b"] == [True, False, False]
    assert (row["passed_samples"], row["total_samples"]) == (4, 9)
    pass_rate = row["pass_rate"]
    assert pass_rate["estimate"] == pytest.approx(4 / 9)
    assert 0 < pass_rate["low"] < pass_rate["estimate"] < pass_rate["high"] < 1
    # route-weighted: 10·1 + 20·(1/3) + 30·0 = 16.67 of 60 routes
    score = row["score"]
    assert score["weighted"] is True
    assert score["estimate"] == pytest.approx(16.6667 / 60, abs=1e-4)
    assert score["low"] <= score["estimate"] <= score["high"]
    assert row["verified_routes"] == pytest.approx(16.6667, abs=1e-3)
    # cost and time are per sample; cost per verified route divides them out
    assert row["cost_usd"] == pytest.approx(6.0)
    assert row["duration_seconds"] == pytest.approx(360.0)
    assert row["cost_per_verified_route"] == pytest.approx(6.0 / 16.6667, abs=1e-4)
    # the representative sample keeps the per-task gate tables working
    cell = data["cells"][("task-b", "codex-luna-with-sanka")]
    assert cell["candidate_id"] == "codex-luna-with-sanka-s1"
    assert len(cell["samples"]) == 3


def test_unweighted_rows_report_task_weighted_scores(sampled_reports: Path) -> None:
    data = collect(sampled_reports)
    (row,) = data["rows"]
    assert row["score"]["weighted"] is False
    assert row["score"]["estimate"] == pytest.approx(4 / 9)
    assert row["verified_routes"] is None
    assert row["cost_per_verified_route"] is None


def test_renderers_print_intervals_and_partial_cells(sampled_reports: Path) -> None:
    data = collect(sampled_reports, {"task-a": 10, "task-b": 20, "task-c": 30})
    page = render_html(data)
    assert 'class="cell cell-partial"' in page
    assert "1/3 samples fully migrated" in page
    assert "4/9" in page
    assert "% of routes [" in page
    assert "/verified route" in page
    assert "3 independent unattended attempts per cell" in page
    svg = render_svg(data)
    assert "4/9 · " in svg and "% of routes [" in svg
    # deterministic: the bootstrap is seeded
    assert render_html(data) == render_html(collect(sampled_reports, data["route_weights"]))
