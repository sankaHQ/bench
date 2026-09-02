"""Command-line interface for Sanka Migration Bench."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sanka_bench.docker import DockerEvaluationError, evaluate_docker, repository_root
from sanka_bench.evaluator import EvaluationError, evaluate_local
from sanka_bench.report import ReportError, write_report
from sanka_bench.schema import SchemaError, load_and_validate, load_schema


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sanka-bench")
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate", help="validate all task and candidate manifests")
    validate.add_argument("--root", type=Path, default=repository_root())

    evaluate = commands.add_parser("evaluate", help="evaluate one candidate against one task")
    evaluate.add_argument("--task", type=Path, required=True)
    evaluate.add_argument("--candidate", type=Path, required=True)
    evaluate.add_argument("--runner", choices=("docker", "local"), default="docker")
    evaluate.add_argument("--output", type=Path)
    evaluate.add_argument(
        "--require-pass",
        action="store_true",
        help="exit non-zero when the candidate is valid but not fully migrated",
    )

    report = commands.add_parser(
        "report", help="render evaluation reports into a static HTML page and summary SVG"
    )
    report.add_argument("--reports", type=Path, default=Path("reports"))
    report.add_argument("--html", type=Path, default=Path("reports/index.html"))
    report.add_argument("--svg", type=Path, default=Path("reports/summary.svg"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate":
            return _validate(args.root)
        if args.command == "report":
            return _report(args)
        return _evaluate(args)
    except (
        DockerEvaluationError,
        EvaluationError,
        ReportError,
        SchemaError,
        OSError,
        ValueError,
    ) as exc:
        print(f"sanka-bench: {exc}")
        return 2


def _validate(root: Path) -> int:
    root = root.resolve()
    for name in ("task", "candidate", "result"):
        load_schema(name)
    task_paths = sorted(root.glob("tasks/**/task.yaml"))
    candidate_paths = sorted(root.glob("baselines/**/candidate.yaml"))
    if not task_paths:
        raise SchemaError(f"no task manifests found under {root}")
    if not candidate_paths:
        raise SchemaError(f"no candidate manifests found under {root}")
    for path in task_paths:
        load_and_validate(path, "task")
    for path in candidate_paths:
        load_and_validate(path, "candidate")
    print(
        f"validated {len(task_paths)} task(s), {len(candidate_paths)} candidate(s), and 3 schema(s)"
    )
    return 0


def _report(args: argparse.Namespace) -> int:
    data = write_report(args.reports.resolve(), args.html.resolve(), args.svg.resolve())
    migrated = sum(
        1 for row in data["rows"] if row["covered"] and len(row["migrated"]) == len(row["covered"])
    )
    print(
        f"report: {len(data['tasks'])} task(s), {len(data['rows'])} approach(es), "
        f"{migrated} approach(es) fully migrated everywhere -> {args.html}"
    )
    return 0


def _evaluate(args: argparse.Namespace) -> int:
    output = args.output.resolve() if args.output else None
    if args.runner == "docker":
        result = evaluate_docker(args.task, args.candidate, output_path=output)
    else:
        result = evaluate_local(args.task, args.candidate)
        _write_result(result, output)
    print(
        f"{result['candidate_id']}: status={result['status']} "
        f"fully_migrated={str(result['fully_migrated']).lower()}"
    )
    if args.require_pass and not result["fully_migrated"]:
        return 1
    return 0


def _write_result(result: dict[str, Any], output: Path | None) -> None:
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output is None:
        print(rendered, end="")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
