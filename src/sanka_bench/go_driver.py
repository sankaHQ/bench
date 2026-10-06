"""Reuse pinned source observations while replacing only candidate serving."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

from sanka_bench.go_guard import request
from sanka_bench.workspace_effects import workspace_snapshot


def merge_native(evidences: list[dict[str, Any]]) -> dict[str, Any]:
    native = dict(evidences[-1])
    for key in ("app_is_fiber", "fiber_dispatch_observed", "endpoint_in_workspace"):
        native[key] = all(item.get(key) is True for item in evidences)
    for key in ("forbidden_imports", "process_events", "socket_events"):
        native[key] = sorted({event for item in evidences for event in item.get(key) or []})
    return native


def main(evaluation: Path) -> int:
    spec = importlib.util.spec_from_file_location("bench_go_oracle", evaluation / "oracle.py")
    if spec is None or spec.loader is None:
        raise ValueError("missing trusted source oracle")
    oracle: Any = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(oracle)
    args = oracle._parser().parse_args()
    workspace = args.workspace.resolve()
    if args.mode == "candidate":
        policy = json.loads(args.policy)
        binary = Path(policy["go_binary"])

        def guarded(_workspace: Path, scenario: Any, _policy: str) -> dict[str, Any]:
            payload = json.loads(scenario) if isinstance(scenario, str) else scenario
            return request(binary, workspace, args.database.resolve(), payload)

        oracle._guarded_candidate_request = guarded
        if hasattr(oracle, "_merge_native"):
            oracle._merge_native = merge_native
        oracle.workspace_snapshot = lambda _path: workspace_snapshot(workspace)
    # Never import candidate-modified Python models, migrations, or settings.
    index = sys.argv.index("--workspace")
    sys.argv[index + 1] = str(evaluation.parent / "source")
    return int(oracle.main())
