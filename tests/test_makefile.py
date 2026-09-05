from __future__ import annotations

import shlex
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


def test_full_suite_partitions_test_files_and_flask_parameters_exactly_once(
    repository_root: Path,
) -> None:
    commands = _dry_run(repository_root, "test")
    covered: list[Path] = []
    flask_parameters: list[str] = []
    for line in commands.splitlines():
        if "python -m pytest" not in line:
            continue
        arguments = shlex.split(line)
        if "--ignore-glob=tests/test_evaluator*.py" in arguments:
            covered.extend(
                path
                for path in (repository_root / "tests").rglob("test_*.py")
                if not path.name.startswith("test_evaluator")
            )
        elif "tests/test_evaluator_flask.py" in arguments:
            if not flask_parameters:
                covered.append(repository_root / "tests/test_evaluator_flask.py")
            flask_parameters.append(arguments[arguments.index("-k") + 1])
        else:
            covered.extend(repository_root / arg for arg in arguments if arg.endswith(".py"))
    assert sorted(covered) == sorted((repository_root / "tests").rglob("test_*.py"))
    assert sorted(flask_parameters) == sorted(
        path.parent.name for path in (repository_root / "tasks/drf-flask").glob("*/task.yaml")
    )
    assert "-j2" in commands


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
