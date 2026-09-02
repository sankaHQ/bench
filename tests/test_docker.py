from __future__ import annotations

from pathlib import Path

import pytest

from sanka_bench import docker
from sanka_bench.process import CommandResult


def _result(argv: list[str], returncode: int, *, stderr: str = "") -> CommandResult:
    return CommandResult(tuple(argv), returncode, "", stderr)


def test_evaluator_image_reuses_the_content_addressed_image(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[list[str]] = []

    monkeypatch.setattr(docker, "digest_tree", lambda root: "sha256:0123456789abcdefrest")

    def fake_run(argv: list[str], **kwargs: object) -> CommandResult:
        calls.append(argv)
        return _result(argv, 0)

    monkeypatch.setattr(docker, "run_command", fake_run)

    assert docker._ensure_evaluator_image(tmp_path) == "sanka-bench:0123456789abcdef"
    assert calls == [["docker", "image", "inspect", "sanka-bench:0123456789abcdef"]]


def test_evaluator_image_builds_once_when_the_tag_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[list[str]] = []

    monkeypatch.setattr(docker, "digest_tree", lambda root: "sha256:fedcba9876543210rest")

    def fake_run(argv: list[str], **kwargs: object) -> CommandResult:
        calls.append(argv)
        return _result(argv, 1 if argv[:3] == ["docker", "image", "inspect"] else 0)

    monkeypatch.setattr(docker, "run_command", fake_run)

    assert docker._ensure_evaluator_image(tmp_path) == "sanka-bench:fedcba9876543210"
    assert calls == [
        ["docker", "image", "inspect", "sanka-bench:fedcba9876543210"],
        [
            "docker",
            "build",
            "--pull=false",
            "--tag",
            "sanka-bench:fedcba9876543210",
            ".",
        ],
    ]


def test_evaluator_image_reports_a_failed_build(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(docker, "digest_tree", lambda root: "sha256:badbadbadbadbadbrest")

    def fake_run(argv: list[str], **kwargs: object) -> CommandResult:
        if argv[:3] == ["docker", "image", "inspect"]:
            return _result(argv, 1)
        return _result(argv, 1, stderr="build exploded")

    monkeypatch.setattr(docker, "run_command", fake_run)

    with pytest.raises(docker.DockerEvaluationError, match="build exploded"):
        docker._ensure_evaluator_image(tmp_path)
