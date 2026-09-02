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
