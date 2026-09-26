from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def _dry_run(repository_root: Path, target: str) -> str:
    completed = subprocess.run(
        ["make", "--dry-run", "TEST_WORKERS=2", target],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def test_local_baseline_target_is_scoped_to_one_task(repository_root: Path) -> None:
    output = _dry_run(repository_root, "baselines-008")

    assert "drf-fastapi-008" in output
    assert "drf-fastapi-007" not in output
    assert output.count("--candidate") == 1
    assert "noop compatibility-bridge native-reference sanka-native" in output


def test_docker_baseline_target_keeps_the_complete_task_inventory(
    repository_root: Path,
) -> None:
    output = _dry_run(repository_root, "docker-baselines-001")

    assert "--runner docker" in output
    assert "drf-fastapi-001" in output
    assert output.count("--candidate") == 1
    assert "native-reference" in output
    assert "sanka-native" in output
    assert "claude-code" not in output  # agent candidates are run artifacts, not baselines


@pytest.mark.parametrize("workers", ["", "auto", "0", "8"])
def test_full_suite_rejects_unbounded_workers(repository_root: Path, workers: str) -> None:
    result = subprocess.run(
        ["make", "--dry-run", f"TEST_WORKERS={workers}", "test"],
        cwd=repository_root,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "TEST_WORKERS must be" in result.stderr
