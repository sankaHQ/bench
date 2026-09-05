from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml

TASKS = [f"{index:03d}" for index in range(1, 12)]


def test_baseline_workflow_shards_every_task_and_preserves_aggregate_gates(
    repository_root: Path,
) -> None:
    workflow = cast(
        dict[str, Any],
        yaml.safe_load((repository_root / ".github" / "workflows" / "ci.yml").read_text()),
    )
    jobs = workflow["jobs"]

    for job_name in ("local-baseline-shard", "docker-baseline-shard"):
        strategy = jobs[job_name]["strategy"]
        assert strategy["fail-fast"] is False
        assert strategy["max-parallel"] == 5
        assert strategy["matrix"]["task"] == TASKS

    assert jobs["check"]["needs"] == ["unit", "local-baseline-shard"]
    assert jobs["docker-baselines"]["needs"] == ["docker-baseline-shard"]


def test_converter_regression_uses_exact_public_source_and_private_fixture_token(
    repository_root: Path,
) -> None:
    path = repository_root / ".github/workflows/converter-regression.yml"
    # BaseLoader preserves the YAML 1.2 "on" key and scalar spellings.
    workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["on"]["workflow_dispatch"]["inputs"]["extensions_sha"]["required"] == "true"
    steps = workflow["jobs"]["converter"]["steps"]
    assert 'test "$GITHUB_REF" = refs/heads/main' in steps[0]["run"]
    assert "^[0-9a-f]{40}$" in steps[0]["run"]
    checkouts = [step["with"] for step in steps if "actions/checkout@" in step.get("uses", "")]
    assert checkouts == [
        {
            "repository": "sankaHQ/extensions",
            "ref": "${{ inputs.extensions_sha }}",
            "path": "extensions",
            "persist-credentials": "false",
        },
        {
            "repository": "sankaHQ/bench",
            "ref": "${{ steps.benchmark.outputs.revision }}",
            "path": "bench",
            "persist-credentials": "false",
        },
    ]
    assert 'test "$(git -C extensions rev-parse HEAD)" = "$EXTENSIONS_SHA"' in steps[2]["run"]
    assert "secrets." not in path.read_text()
    assert "run_converter_bench.py" in steps[-2]["run"]
    assert 'test -z "$(git -C extensions status --porcelain)"' in steps[-2]["run"]
    assert steps[-1]["if"] == "${{ always() }}"
    assert steps[-1]["with"]["if-no-files-found"] == "error"
