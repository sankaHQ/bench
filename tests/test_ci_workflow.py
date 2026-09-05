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
        assert strategy["max-parallel"] == (10 if job_name == "docker-baseline-shard" else 5)
        assert strategy["matrix"]["task"] == TASKS

    assert jobs["check"]["needs"] == ["unit", "local-baseline-shard"]
    assert jobs["docker-baselines"]["needs"] == ["docker-baseline-shard"]
    unit_commands = [step.get("run", "") for step in jobs["unit"]["steps"]]
    assert "make lint typecheck test-unit" in unit_commands
    assert "make check" not in unit_commands  # Evaluator tests belong to the task shards.
    shard_commands = [step.get("run", "") for step in jobs["local-baseline-shard"]["steps"]]
    assert "make test-evaluator-${{ matrix.task }}" in shard_commands
    assert "make baselines-${{ matrix.task }}" not in shard_commands
    assert workflow["concurrency"]["cancel-in-progress"] == (
        "${{ github.event_name == 'pull_request' }}"
    )
