"""Render benchmark result reports into a static HTML page and summary SVG.

Reads every ``*.json`` result in a reports directory (as produced by
``sanka-bench evaluate --output``), groups local and Docker runs of the same
candidate, and renders:

- a hero tally — tasks fully migrated per approach — the headline visual;
- a diagnostic scenario-parity table (Migration Quality Score v0.3 preview):
  per-scenario behavior/database/native rates published beside the binary
  verdict, so a 31/32 near-miss is visible next to the cliff it fell off —
  never blended into the headline;
- a per-task hard-gate matrix, where a compatibility facade shows green
  behavior next to a red native-evidence gate;
- a provenance footer (evaluator versions, repeat counts, runner parity).

The output is deterministic for a given set of reports: no timestamps, sorted
iteration everywhere. The headline metric is the binary Fully Migrated count;
gates are never blended into a compensating score.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sanka_bench.statistics import bootstrap_interval, weighted_score, wilson_interval

_SAMPLE_SUFFIX = re.compile(r"-s(\d+)$")

GATE_ORDER = (
    ("source_qualified", "SRC", "Source qualified"),
    ("regression_tests", "REG", "Existing tests kept passing"),
    ("target_boot", "BOOT", "Target boots"),
    ("native_target", "NATIVE", "Native serving evidence"),
    ("behavior_parity", "HTTP", "HTTP behavior parity"),
    ("database_parity", "DB", "Database state parity"),
    ("side_effect_parity", "FX", "Side-effect parity"),
    ("deterministic", "DET", "Deterministic across clean runs"),
)

_DIAGNOSTIC_FIELDS = {
    "behavior": "behavioral_parity",
    "database": "database_parity",
    "native": "native_compliance",
}

_FAMILY_ORDER = (
    "noop",
    "compatibility-bridge",
    "claude-code-alone",
    "claude-code-with-sanka",
    "claude-code-with-sanka-readiness-aware",
    "sanka-native",
    "native-reference",
)
_FAMILY_LABELS = {
    "noop": "No-op (unchanged source)",
    "compatibility-bridge": "Sanka compatibility bridge",
    "claude-code-alone": "Claude Code, agent alone",
    "claude-code-with-sanka": "Claude Code + Sanka",
    "claude-code-with-sanka-readiness-aware": "Claude Code + readiness-aware Sanka",
    "sanka-native": "Sanka native converter",
    "native-reference": "Human native reference",
}


class ReportError(RuntimeError):
    """Raised when the reports directory holds nothing renderable."""


def family_key(candidate_id: str) -> str:
    """Group every sample of one approach together (``…-s2`` is sample 2 of ``…``)."""
    if "compatibility-bridge" in candidate_id:
        return "compatibility-bridge"
    return _SAMPLE_SUFFIX.sub("", candidate_id)


def sample_index(candidate_id: str) -> int:
    match = _SAMPLE_SUFFIX.search(candidate_id)
    return int(match.group(1)) if match else 1


def family_label(family: str) -> str:
    return _FAMILY_LABELS.get(family, family)


def collect(reports_dir: Path, route_weights: Mapping[str, int] | None = None) -> dict[str, Any]:
    """Aggregate result files into per-approach rows.

    A cell is one (task, approach); it may hold several samples (``candidate_id``
    suffixed ``-s<k>``), each with a local and/or Docker result. Rows carry the
    task-sample pass rate with a Wilson interval, the route-weighted score with a
    bootstrap interval when route weights are given (task-weighted otherwise), and the
    agent's cost and time per sample beside cost per verified route. See
    ``docs/measurement-design.md``.
    """
    cells: dict[tuple[str, str], dict[str, Any]] = {}
    for path in sorted(reports_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or "hard_gates" not in payload:
            continue
        task_id = str(payload.get("task_id", ""))
        candidate_id = str(payload.get("candidate_id", ""))
        if not task_id or not candidate_id:
            continue
        runner = "docker" if path.stem.endswith("-docker") else "local"
        cell = cells.setdefault(
            (task_id, family_key(candidate_id)),
            {"candidate_id": candidate_id, "local": None, "docker": None, "samples": {}},
        )
        sample = cell["samples"].setdefault(
            sample_index(candidate_id),
            {"candidate_id": candidate_id, "local": None, "docker": None},
        )
        sample[runner] = payload
    if not cells:
        raise ReportError(f"no benchmark results found in {reports_dir}")
    for cell in cells.values():
        ordered = [cell["samples"][index] for index in sorted(cell["samples"])]
        cell["samples"] = ordered
        # the first sample stays the representative for the per-task gate tables
        cell["candidate_id"] = ordered[0]["candidate_id"]
        cell["local"] = ordered[0]["local"]
        cell["docker"] = ordered[0]["docker"]

    tasks = sorted({task for task, _ in cells})
    seen_families = {family for _, family in cells}
    families = [family for family in _FAMILY_ORDER if family in seen_families]
    families.extend(sorted(seen_families - set(_FAMILY_ORDER)))
    weights = dict(route_weights) if route_weights else None

    rows: list[dict[str, Any]] = []
    for family in families:
        migrated: list[str] = []
        covered: list[str] = []
        outcomes: dict[str, list[bool]] = {}
        cost_usd = 0.0
        duration_seconds = 0.0
        has_stats = False
        result_count = 0
        diagnostic = {key: [0, 0] for key in _DIAGNOSTIC_FIELDS}
        has_metrics = False
        for task in tasks:
            entry = cells.get((task, family))
            if entry is None:
                continue
            task_outcomes: list[bool] = []
            for sample in entry["samples"]:
                result = sample["local"] or sample["docker"]
                if result is None:
                    continue
                result_count += 1
                task_outcomes.append(result.get("fully_migrated") is True)
                stats = result.get("provenance", {}).get("candidate_stats")
                if isinstance(stats, dict):
                    has_stats = True
                    cost_usd += float(stats.get("cost_usd") or 0)
                    duration_seconds += float(stats.get("duration_seconds") or 0)
                metrics = result.get("metrics")
                if isinstance(metrics, dict):
                    for key, field in _DIAGNOSTIC_FIELDS.items():
                        fraction = metrics.get(field)
                        if isinstance(fraction, dict):
                            has_metrics = True
                            diagnostic[key][0] += int(fraction.get("passed") or 0)
                            diagnostic[key][1] += int(fraction.get("total") or 0)
            if not task_outcomes:
                continue
            covered.append(task)
            outcomes[task] = task_outcomes
            if all(task_outcomes):
                migrated.append(task)
        samples = max((len(values) for values in outcomes.values()), default=1)
        passed_samples = sum(sum(1 for passed in values if passed) for values in outcomes.values())
        total_samples = sum(len(values) for values in outcomes.values())
        task_weights = [weights.get(task, 0) if weights else 1 for task in covered]
        weighted = bool(weights)
        score = bootstrap_interval([outcomes[task] for task in covered], task_weights)
        total_weight = sum(task_weights)
        verified_routes = (
            weighted_score([outcomes[task] for task in covered], task_weights) * total_weight
            if weighted
            else None
        )
        per_sample = samples if samples else 1
        row_cost = cost_usd / per_sample if has_stats else None
        rows.append(
            {
                "family": family,
                "label": family_label(family),
                "migrated": migrated,
                "covered": covered,
                "outcomes": outcomes,
                "samples": samples,
                "passed_samples": passed_samples,
                "total_samples": total_samples,
                "pass_rate": wilson_interval(passed_samples, total_samples).to_dict(),
                "score": {**score.to_dict(), "weighted": weighted},
                "verified_routes": verified_routes,
                "cost_usd": row_cost,
                "duration_seconds": duration_seconds / per_sample if has_stats else None,
                "cost_per_verified_route": (
                    row_cost / verified_routes if row_cost is not None and verified_routes else None
                ),
                "diagnostic": diagnostic if has_metrics else None,
            }
        )

    parity_checked = 0
    parity_matched = 0
    versions: set[str] = set()
    for cell in cells.values():
        for sample in cell["samples"]:
            for result in (sample["local"], sample["docker"]):
                if result is not None:
                    versions.add(str(result.get("provenance", {}).get("evaluator_version", "")))
            if sample["local"] is not None and sample["docker"] is not None:
                parity_checked += 1
                if (
                    sample["local"]["hard_gates"] == sample["docker"]["hard_gates"]
                    and sample["local"]["fully_migrated"] == sample["docker"]["fully_migrated"]
                ):
                    parity_matched += 1

    return {
        "tasks": tasks,
        "rows": rows,
        "cells": cells,
        "samples": max((row["samples"] for row in rows), default=1),
        "route_weights": weights,
        "parity_checked": parity_checked,
        "parity_matched": parity_matched,
        "evaluator_versions": sorted(version for version in versions if version),
    }


def count_label(row: dict[str, Any]) -> str:
    """``migrated/covered`` for single samples, ``passed/total task-samples`` otherwise."""
    if not row["covered"]:
        return "—"
    if row.get("samples", 1) > 1:
        return f"{row['passed_samples']}/{row['total_samples']}"
    return f"{len(row['migrated'])}/{len(row['covered'])}"


def interval_label(row: dict[str, Any]) -> str:
    """Score with its bootstrap interval; empty for single-sample, unweighted rows."""
    score = row.get("score") or {}
    if not row["covered"] or not (row.get("samples", 1) > 1 or score.get("weighted")):
        return ""
    unit = "routes" if score.get("weighted") else "tasks"
    return (
        f"{score['estimate'] * 100:.1f}% of {unit} "
        f"[{score['low'] * 100:.1f}, {score['high'] * 100:.1f}]"
    )


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _tally_row(row: dict[str, Any], tasks: list[str]) -> str:
    cells = []
    for task in tasks:
        if task not in row["covered"]:
            cells.append(
                f'<span class="cell cell-absent" title="{_esc(task)}: no candidate"></span>'
            )
            continue
        outcomes = row["outcomes"].get(task) or []
        passed = sum(1 for value in outcomes if value)
        if len(outcomes) > 1:
            detail = f"{passed}/{len(outcomes)} samples fully migrated"
        else:
            detail = "fully migrated" if passed else "not fully migrated"
        if passed == len(outcomes):
            klass = "cell-pass"
        elif passed:
            klass = "cell-partial"
        else:
            klass = "cell-fail"
        cells.append(f'<span class="cell {klass}" title="{_esc(task)}: {_esc(detail)}"></span>')
    count = count_label(row)
    stats_note = ""
    if row.get("cost_usd") is not None:
        minutes = (row.get("duration_seconds") or 0) / 60
        per_route = row.get("cost_per_verified_route")
        route_note = f" · ${per_route:.3f}/verified route" if per_route is not None else ""
        stats_note = (
            f'<span class="tally-stats">${row["cost_usd"]:.2f}'
            f" · {minutes:.0f} min agent time{route_note}</span>"
        )
    interval = interval_label(row)
    interval_note = f'<span class="tally-interval">{_esc(interval)}</span>' if interval else ""
    return (
        '<div class="tally-row">'
        f'<span class="tally-label">{_esc(row["label"])}</span>'
        f'<span class="tally-cells">{"".join(cells)}</span>'
        f'<span class="tally-count">{_esc(count)}</span>'
        f"{interval_note}"
        f"{stats_note}"
        "</div>"
    )


def _scenario_summary(result: dict[str, Any]) -> str:
    metrics = result.get("metrics")
    if not isinstance(metrics, dict):
        return "—"
    parts = []
    for label, field in (("HTTP", "behavioral_parity"), ("DB", "database_parity")):
        fraction = metrics.get(field)
        if isinstance(fraction, dict):
            parts.append(f"{label} {fraction.get('passed')}/{fraction.get('total')}")
    return " · ".join(parts) if parts else "—"


def _gate_table(task: str, data: dict[str, Any]) -> str:
    heads = "".join(
        f'<th scope="col"><abbr title="{_esc(title)}">{_esc(abbr)}</abbr></th>'
        for _, abbr, title in GATE_ORDER
    )
    body_rows = []
    for family in [row["family"] for row in data["rows"]]:
        cell = data["cells"].get((task, family))
        if cell is None:
            continue
        result = cell["local"] or cell["docker"]
        gates = result["hard_gates"]
        cells_html = []
        for key, _, title in GATE_ORDER:
            passed = bool(gates.get(key))
            glyph, cls, word = ("✓", "gate-pass", "pass") if passed else ("✗", "gate-fail", "FAIL")
            cells_html.append(
                f'<td class="{cls}" title="{_esc(title)}: {word}">'
                f'<span aria-hidden="true">{glyph}</span>'
                f'<span class="sr-only">{word}</span></td>'
            )
        verdict = (
            '<span class="pill pill-pass">fully migrated</span>'
            if result.get("fully_migrated")
            else '<span class="pill pill-fail">not migrated</span>'
        )
        body_rows.append(
            f'<tr><th scope="row">{_esc(family_label(family))}</th>'
            f"{''.join(cells_html)}"
            f'<td class="scenario-summary">{_esc(_scenario_summary(result))}</td>'
            f"<td>{verdict}</td></tr>"
        )
    return (
        f'<section class="task"><h3>{_esc(task)}</h3>'
        '<div class="table-wrap"><table>'
        f'<thead><tr><th scope="col">Candidate</th>{heads}'
        '<th scope="col"><abbr title="Per-scenario parity (diagnostic; a task passes '
        'only when every scenario passes)">Scenarios</abbr></th>'
        '<th scope="col">Verdict</th></tr></thead>'
        f"<tbody>{''.join(body_rows)}</tbody></table></div></section>"
    )


def _diagnostic_table(data: dict[str, Any]) -> str:
    rows_with_metrics = [row for row in data["rows"] if row.get("diagnostic")]
    if not rows_with_metrics:
        return ""
    body_rows = []
    for row in rows_with_metrics:
        cells = []
        for key in _DIAGNOSTIC_FIELDS:
            passed, total = row["diagnostic"][key]
            rate = f"{passed / total:.1%}" if total else "—"
            cells.append(
                f'<td class="diag-cell">{passed}/{total}'
                f'<span class="diag-rate"> ({rate})</span></td>'
            )
        body_rows.append(f'<tr><th scope="row">{_esc(row["label"])}</th>{"".join(cells)}</tr>')
    return (
        '<h2>Diagnostic scenario parity <span class="tag">score v0.3 preview</span></h2>'
        '<p class="note">Per-scenario pass rates summed across every covered task — the '
        "same evidence the binary verdict gates on, published so a near-miss (31/32 "
        "scenarios) is distinguishable from an empty candidate. Diagnostic only: the "
        "headline stays binary per task, and these rates never compensate for a failed "
        "hard gate.</p>"
        '<div class="table-wrap"><table>'
        '<thead><tr><th scope="col">Candidate</th>'
        '<th scope="col">HTTP behavior</th><th scope="col">Database</th>'
        '<th scope="col">Native serving</th></tr></thead>'
        f"<tbody>{''.join(body_rows)}</tbody></table></div>"
    )


def render_html(data: dict[str, Any]) -> str:
    tasks = data["tasks"]
    tally = "".join(_tally_row(row, tasks) for row in data["rows"])
    diagnostics = _diagnostic_table(data)
    tables = "".join(_gate_table(task, data) for task in tasks)
    parity = (
        f"{data['parity_matched']}/{data['parity_checked']} local↔Docker runs agree"
        if data["parity_checked"]
        else "single-runner results"
    )
    versions = ", ".join(data["evaluator_versions"]) or "unknown"
    agent_note = ""
    if any(row.get("cost_usd") is not None for row in data["rows"]):
        samples = int(data.get("samples") or 1)
        attempts = (
            "single unattended attempts (pass@1)"
            if samples == 1
            else f"{samples} independent unattended attempts per cell (pass@1 mean, "
            "Wilson interval on task-samples, bootstrap interval on the route-weighted score)"
        )
        agent_note = (
            f'<p class="note">Official agent rows are {attempts} with '
            "the same model, turn budget, and contract; the ordinary with-Sanka prompt offers "
            "the Sanka CLI with readiness-aware usage guidance. Readiness-aware rows are a "
            "separately labelled "
            "diagnostic arm. Dollar and time figures are the agent's own reported totals "
            "across the covered tasks. The Sanka native converter and the controls run in "
            "seconds at no model cost.</p>"
        )
    bridge_note = ""
    if any(row["family"] == "compatibility-bridge" for row in data["rows"]):
        bridge_note = (
            '<p class="note">The compatibility bridge is a permanent negative control: '
            "it preserves behavior by dispatching into the original application, and the "
            "native-evidence gate rejects it anyway. A green HTTP column beside a red "
            "NATIVE column is the anti-facade guarantee at work.</p>"
        )
    return f"""<title>Sanka Bench Report</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
:root {{
  --surface: #fcfcfb; --surface-2: #f3f3f0;
  --ink: #0b0b0b; --ink-2: #52514e; --hairline: #e3e2dd;
  --accent: #2a78d6; --good: #0ca30c; --critical: #d03b3b;
  --cell-empty: #e9e8e3;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --surface: #1a1a19; --surface-2: #232322;
    --ink: #ffffff; --ink-2: #c3c2b7; --hairline: #33332e;
    --accent: #3987e5; --good: #0ca30c; --critical: #d03b3b;
    --cell-empty: #2c2c2a;
  }}
}}
:root[data-theme="dark"] {{
  --surface: #1a1a19; --surface-2: #232322;
  --ink: #ffffff; --ink-2: #c3c2b7; --hairline: #33332e;
  --accent: #3987e5; --good: #0ca30c; --critical: #d03b3b;
  --cell-empty: #2c2c2a;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; background: var(--surface); color: var(--ink);
  font: 15px/1.6 "IBM Plex Sans", system-ui, sans-serif;
}}
main {{ max-width: 880px; margin: 0 auto; padding: 40px 24px 64px; }}
header {{ border-bottom: 1px solid var(--hairline); padding-bottom: 20px; margin-bottom: 28px; }}
h1 {{
  font: 600 22px/1.3 "IBM Plex Mono", ui-monospace, monospace;
  margin: 0 0 6px; letter-spacing: -0.01em; text-wrap: balance;
}}
.subtitle {{ color: var(--ink-2); margin: 0; max-width: 65ch; }}
h2 {{
  font: 600 13px/1.4 "IBM Plex Mono", ui-monospace, monospace;
  text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--ink-2); margin: 36px 0 14px;
}}
h3 {{ font: 500 15px/1.4 "IBM Plex Mono", ui-monospace, monospace; margin: 24px 0 8px; }}
.tally {{ display: flex; flex-direction: column; gap: 10px; }}
.tally-row {{ display: flex; align-items: center; flex-wrap: wrap; gap: 8px 14px; }}
.tally-label {{ flex: 0 0 240px; font-size: 14px; }}
.tally-cells {{ display: flex; gap: 2px; }}
.cell {{ width: 34px; height: 16px; border-radius: 4px; }}
.cell-pass {{ background: var(--accent); }}
.cell-fail {{ background: var(--cell-empty); box-shadow: inset 0 0 0 1px var(--hairline); }}
.cell-partial {{
  background: linear-gradient(90deg, var(--accent) 50%, var(--cell-empty) 50%);
  box-shadow: inset 0 0 0 1px var(--hairline);
}}
.cell-absent {{
  background: transparent; box-shadow: inset 0 0 0 1px var(--hairline); opacity: .45;
}}
.tally-count {{
  font: 500 14px/1 "IBM Plex Mono", ui-monospace, monospace;
  font-variant-numeric: tabular-nums; color: var(--ink-2);
}}
.tally-interval {{
  font-family: "IBM Plex Mono", monospace; font-size: 12px; color: #52514e; margin-left: 10px;
}}
.tally-stats {{
  font: 400 12px/1 "IBM Plex Mono", ui-monospace, monospace;
  font-variant-numeric: tabular-nums; color: var(--ink-2); opacity: .85;
}}
.legend {{ color: var(--ink-2); font-size: 13px; margin-top: 10px; }}
.legend .cell {{ display: inline-block; vertical-align: -3px; width: 16px; margin-right: 4px; }}
.table-wrap {{ overflow-x: auto; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13.5px; }}
th, td {{ text-align: left; padding: 7px 10px; border-bottom: 1px solid var(--hairline); }}
thead th {{
  font: 500 11px/1.4 "IBM Plex Mono", ui-monospace, monospace;
  text-transform: uppercase; letter-spacing: 0.06em; color: var(--ink-2);
}}
tbody th {{ font-weight: 500; white-space: nowrap; }}
abbr {{ text-decoration: none; cursor: help; }}
td.gate-pass, td.gate-fail {{ font: 600 13px/1 "IBM Plex Mono", ui-monospace, monospace; }}
td.gate-pass {{ color: var(--good); }}
td.gate-fail {{ color: var(--critical); }}
td.scenario-summary, td.diag-cell {{
  font: 400 12.5px/1.4 "IBM Plex Mono", ui-monospace, monospace;
  font-variant-numeric: tabular-nums; white-space: nowrap; color: var(--ink-2);
}}
.diag-rate {{ opacity: .7; }}
.tag {{
  font: 500 10px/1 "IBM Plex Mono", ui-monospace, monospace;
  text-transform: none; letter-spacing: 0.02em; color: var(--accent);
  border: 1px solid var(--accent); border-radius: 999px; padding: 2px 7px;
  vertical-align: 2px; margin-left: 6px;
}}
.pill {{
  font: 500 11px/1 "IBM Plex Mono", ui-monospace, monospace;
  padding: 4px 8px; border-radius: 999px; white-space: nowrap;
}}
.pill-pass {{ color: var(--good); box-shadow: inset 0 0 0 1px var(--good); }}
.pill-fail {{ color: var(--critical); box-shadow: inset 0 0 0 1px var(--critical); }}
.note {{ color: var(--ink-2); font-size: 13.5px; max-width: 65ch; }}
footer {{
  margin-top: 44px; padding-top: 16px; border-top: 1px solid var(--hairline);
  color: var(--ink-2); font: 400 12.5px/1.7 "IBM Plex Mono", ui-monospace, monospace;
}}
.sr-only {{
  position: absolute; width: 1px; height: 1px; overflow: hidden;
  clip: rect(0 0 0 0); white-space: nowrap;
}}
</style>
<main>
<header>
<h1>Sanka Migration Bench</h1>
<p class="subtitle">Tool-neutral repository-migration benchmark. A task counts as
<strong>fully migrated</strong> only when every hard gate passes — behavioral,
database, and side-effect parity with the source application, plus recorded
evidence that the target framework genuinely serves each request. Gates are
never averaged into a compensating score.</p>
</header>
<h2>Tasks fully migrated</h2>
<div class="tally">{tally}</div>
<p class="legend"><span class="cell cell-pass"></span> fully migrated
&nbsp;&nbsp;<span class="cell cell-fail"></span> failed a hard gate
&nbsp;&nbsp;one cell per task ({_esc(len(tasks))} task{"s" if len(tasks) != 1 else ""})</p>
{agent_note}
{bridge_note}
{diagnostics}
<h2>Hard gates by task</h2>
{tables}
<footer>
evaluator {_esc(versions)} · {_esc(parity)} · repeat ≥ 2 clean runs per candidate ·
generated by <code>sanka-bench report</code>
</footer>
</main>
"""


def render_svg(data: dict[str, Any]) -> str:
    tasks = data["tasks"]
    rows = data["rows"]
    row_height = 34
    label_width = 250
    cell_width, cell_height, cell_gap = 44, 16, 2
    width = 720
    height = 52 + row_height * len(rows) + 26
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        'aria-label="Sanka Migration Bench: tasks fully migrated per approach">',
        f'<rect width="{width}" height="{height}" fill="#fcfcfb"/>',
        '<text x="24" y="30" font-family="IBM Plex Mono, monospace" font-size="15" '
        'font-weight="600" fill="#0b0b0b">Sanka Migration Bench — tasks fully migrated</text>',
    ]
    y = 52
    for row in rows:
        cy = y + row_height // 2
        parts.append(
            f'<text x="24" y="{cy + 4}" font-family="IBM Plex Sans, sans-serif" '
            f'font-size="13" fill="#0b0b0b">{_esc(row["label"])}</text>'
        )
        x = label_width
        for task in tasks:
            if task not in row["covered"]:
                fill, stroke = "none", "#e3e2dd"
            elif task in row["migrated"]:
                fill, stroke = "#2a78d6", "none"
            else:
                fill, stroke = "#e9e8e3", "#e3e2dd"
            stroke_attr = f' stroke="{stroke}"' if stroke != "none" else ""
            parts.append(
                f'<rect x="{x}" y="{cy - cell_height // 2}" width="{cell_width}" '
                f'height="{cell_height}" rx="4" fill="{fill}"{stroke_attr}/>'
            )
            x += cell_width + cell_gap
        count = count_label(row)
        interval = interval_label(row)
        label = f"{count} · {interval}" if interval else count
        parts.append(
            f'<text x="{x + 14}" y="{cy + 4}" font-family="IBM Plex Mono, monospace" '
            f'font-size="13" fill="#52514e">{_esc(label)}</text>'
        )
        y += row_height
    parts.append(
        f'<text x="24" y="{height - 10}" font-family="IBM Plex Mono, monospace" '
        f'font-size="10.5" fill="#52514e">one cell per task · a task passes only when every '
        "hard gate passes · generated by sanka-bench report</text>"
    )
    parts.append("</svg>")
    return "".join(parts)


def write_report(
    reports_dir: Path,
    html_path: Path,
    svg_path: Path,
    route_weights: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    data = collect(reports_dir, route_weights)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_html(data), encoding="utf-8")
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    svg_path.write_text(render_svg(data), encoding="utf-8")
    return data
