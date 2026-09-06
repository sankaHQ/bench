"""Matched accuracy and efficiency comparisons from frozen matrix evidence."""

from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
from typing import Any


def _total(rows: list[dict[str, Any]], metric: str) -> float | None:
    values = [row.get(metric) for row in rows]
    if not values or any(
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
        or value < 0
        for value in values
    ):
        return None
    return sum(values)


def compare(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Never drop failures or missing cells from a configuration's denominator."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[row["model_slug"], row["config"]].append(row)
    summaries = []
    for (model, config), group in groups.items():
        baseline = groups.get((model, "alone"), [])
        baseline_by_task = {(row["task"], row["sample"]): row for row in baseline}
        complete = all(isinstance(row.get("passed"), bool) for row in group)
        matched = (
            complete
            and len(baseline) == len(group)
            and all(
                isinstance(
                    baseline_by_task.get((row["task"], row["sample"]), {}).get("passed"), bool
                )
                for row in group
            )
        )
        passed = sum(row.get("passed") is True for row in group)
        weighted = sum(row["route_weight"] for row in group if row.get("passed") is True)
        summary: dict[str, Any] = {
            "model_slug": model,
            "config": config,
            "expected": len(group),
            "scored": sum(isinstance(row.get("passed"), bool) for row in group),
            "pass_at_1": passed / len(group) if complete else None,
            "route_weighted_pass_at_1": weighted / sum(row["route_weight"] for row in group)
            if complete
            else None,
            "paired_regressions": sum(
                baseline_by_task[row["task"], row["sample"]]["passed"] and not row["passed"]
                for row in group
            )
            if matched
            else None,
        }
        metrics = (
            "generation_seconds",
            "end_to_end_seconds",
            "total_tokens",
            "output_tokens",
            "turns",
            "observed_model_responses",
            "tool_calls",
            "infrastructure_retries",
            "cost_usd",
        )
        summary["totals"] = {metric: _total(group, metric) for metric in metrics}
        seconds = summary["totals"]["end_to_end_seconds"]
        summary["serial_successes_per_hour"] = (
            3600 * passed / seconds if complete and seconds else None
        )
        goals: dict[str, bool | None] = {
            "accuracy_at_least_baseline": summary["pass_at_1"]
            >= sum(r["passed"] for r in baseline) / len(baseline)
            if matched
            else None,
            "no_paired_accuracy_regression": summary["paired_regressions"] == 0
            if matched
            else None,
        }
        for name, metric in (
            ("fewer_tokens", "total_tokens"),
            ("faster_generation", "generation_seconds"),
            ("faster_end_to_end", "end_to_end_seconds"),
            ("lower_cost", "cost_usd"),
        ):
            base = _total(baseline, metric)
            value = summary["totals"][metric]
            cost_bases = {row.get("cost_basis") for row in group + baseline}
            comparable = metric != "cost_usd" or (len(cost_bases) == 1 and None not in cost_bases)
            goals[name] = (
                value < base
                if matched and comparable and base is not None and value is not None
                else None
            )
        # Retry incident timing/cost is not part of the final cell telemetry.
        retry_overhead_unknown = any(
            row.get("infrastructure_retries", 0) for row in group + baseline
        )
        if retry_overhead_unknown:
            for name in ("fewer_tokens", "faster_generation", "faster_end_to_end", "lower_cost"):
                goals[name] = None
        base_seconds = _total(baseline, "end_to_end_seconds")
        rate = summary["serial_successes_per_hour"]
        goals["higher_serial_throughput"] = (
            rate > 3600 * sum(r["passed"] for r in baseline) / base_seconds
            if matched and not retry_overhead_unknown and rate is not None and base_seconds
            else None
        )
        summary["goals"] = goals if config != "alone" else {}
        summary["all_goals_met"] = (
            (False if False in goals.values() else None if None in goals.values() else True)
            if config != "alone"
            else None
        )
        summaries.append(summary)
    return summaries


def write_report(manifest: dict[str, Any], root: Path) -> None:
    # Import here so the coordinator can reuse the report without a circular import.
    from run_agent_matrix import (
        artifact_issues,
        artifacts,
        atomic_json,
        build_cells,
        cell_state,
        credential_values,
        load_json,
        secret_hits,
    )

    cells = build_cells(manifest)
    if artifact_issues(root, cells) or secret_hits(root, credential_values(manifest)):
        raise ValueError("Matrix publication failed artifact integrity or credential checks")
    rows = []
    models = {model["slug"]: model for model in manifest["models"]}
    for cell in cells:
        paths = artifacts(root, cell)
        state = cell_state(root, cell)
        report = load_json(paths.report) if state == "terminal" and paths.report.is_file() else {}
        telemetry_path = paths.candidate / "telemetry.json"
        telemetry = load_json(telemetry_path) if telemetry_path.is_file() else {}
        stats = report.get("provenance", {}).get("candidate_stats", {})
        timing = telemetry.get("timing", {})
        row = {
            "model_slug": cell.model_slug,
            "harness": cell.harness,
            "reasoning_effort": models[cell.model_slug].get("reasoning_effort"),
            "actual_model_id": cell.actual_model_id,
            "provider": cell.provider,
            "provider_variant": cell.provider_variant,
            "task": cell.task,
            "sample": cell.sample,
            "config": cell.config,
            "route_weight": cell.route_weight,
            "state": state,
            "passed": report.get("fully_migrated"),
            "input_digest": cell.input_digest,
            "generation_seconds": timing.get("generation_seconds"),
            "end_to_end_seconds": stats.get("end_to_end_seconds"),
            "timing": timing,
            "usage": telemetry.get("usage", {}),
            "total_tokens": telemetry.get("usage", {}).get("total_tokens"),
            "output_tokens": telemetry.get("usage", {}).get("output_tokens"),
            "turns": stats.get("turns"),
            "cost_usd": telemetry.get("cost", {}).get("cost_usd"),
            "cost_basis": telemetry.get("cost", {}).get("basis"),
            "reported_equivalent_cost_usd": telemetry.get("cost", {}).get(
                "reported_equivalent_cost_usd"
            ),
            "infrastructure_retries": telemetry.get("wave", {}).get("attempt", 1) - 1,
            "observed_model_responses": telemetry.get("work", {}).get("observed_model_responses"),
            "tool_calls": telemetry.get("work", {}).get("tool_calls"),
            "treatment": telemetry.get("treatment"),
            "report": str(paths.report.relative_to(root)) if report else None,
        }
        rows.append(row)
    summaries = compare(rows)
    atomic_json(
        root / "matrix.json",
        {
            "schema": "sanka-bench/comparison/v1",
            "benchmark_sha": manifest["benchmark_sha"],
            "sanka_workflow": manifest["execution"].get("sanka_workflow", "availability-v1"),
            "rows": rows,
            "comparisons": summaries,
        },
    )
    lines = [
        "# Benchmark comparison",
        "",
        f"Benchmark: `{manifest['benchmark_sha']}`. "
        f"Workflow: `{manifest['execution'].get('sanka_workflow', 'availability-v1')}`.",
        "",
        "Accuracy uses every scheduled task/sample. Missing evidence remains unknown.",
        "Generation includes Sanka preparation; end-to-end includes evaluation. "
        "Throughput is a serial equivalent, not measured concurrent capacity.",
        "Observed model responses are not provider API request counts. "
        "Cost basis and Claude-equivalent estimates remain separate in matrix.json.",
        "Harness / requested effort: "
        + "; ".join(
            f"{m['slug']}: {m.get('harness') or m.get('agent')} / "
            f"{m.get('reasoning_effort') or 'not pinned'}"
            for m in manifest["models"]
        )
        + ".",
        "If infrastructure retries occurred, efficiency goals remain unknown because "
        "final-cell totals exclude prior incident overhead.",
        "",
        "| Model | Configuration | Scored | pass@1 | Generation (s) | Tokens | Cost (USD) "
        "| Successful tasks/hour (serial) | Goals met |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]

    def display(value: Any) -> str:
        return (
            "unknown"
            if value is None
            else str(round(value, 3))
            if isinstance(value, float)
            else str(value)
        )

    for summary in summaries:
        totals = summary["totals"]
        lines.append(
            "| "
            + " | ".join(
                display(value)
                for value in (
                    summary["model_slug"],
                    summary["config"],
                    f"{summary['scored']}/{summary['expected']}",
                    summary["pass_at_1"],
                    totals["generation_seconds"],
                    totals["total_tokens"],
                    totals["cost_usd"],
                    summary["serial_successes_per_hour"],
                    summary["all_goals_met"],
                )
            )
            + " |"
        )
    for summary in summaries:
        if summary["goals"]:
            lines.extend(
                [
                    "",
                    f"{summary['model_slug']} / {summary['config']}: "
                    + "; ".join(
                        f"{name}={display(value)}" for name, value in summary["goals"].items()
                    ),
                    "",
                ]
            )
    (root / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
