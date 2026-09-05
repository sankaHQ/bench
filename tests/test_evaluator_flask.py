from pathlib import Path

import pytest

from sanka_bench.evaluator import evaluate_local
from sanka_bench.hashing import digest_tree
from sanka_bench.schema import load_and_validate


@pytest.mark.parametrize(
    "task_id", ["drf-flask-001", "drf-flask-002", "drf-flask-003", "drf-flask-004"]
)
def test_flask_controls(repository_root: Path, task_id: str) -> None:
    task_dir = repository_root / "tasks" / "drf-flask" / task_id
    task = load_and_validate(task_dir / "task.yaml", "task")
    assert task["source"]["provenance"]["digest"] == digest_tree(task_dir / "source")
    controls = ["native-reference", "compatibility-bridge", "noop"]
    if task_id == "drf-flask-004":
        controls.append("missing-audit")
    for name in controls:
        result = evaluate_local(task_dir, repository_root / "baselines" / task_id / name)
        assert result["hard_gates"]["source_qualified"], result["errors"]
        if name == "native-reference":
            assert result["fully_migrated"], result
            assert all(result["hard_gates"].values())
        elif name == "compatibility-bridge":
            assert result["hard_gates"]["behavior_parity"], result
            assert result["hard_gates"]["database_parity"], result
            assert not result["hard_gates"]["native_target"]
        elif name == "missing-audit":
            assert result["hard_gates"]["native_target"]
            assert result["hard_gates"]["behavior_parity"]
            assert not result["hard_gates"]["database_parity"]
        else:
            assert not result["hard_gates"]["target_boot"]
        assert result["fully_migrated"] == (name == "native-reference")
