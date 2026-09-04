from __future__ import annotations

from pathlib import Path

from sanka_bench.cli import build_parser, main


def test_validate_command(repository_root: Path) -> None:
    assert main(["validate", "--root", str(repository_root)]) == 0


def test_evaluate_accepts_podman_as_the_container_engine() -> None:
    args = build_parser().parse_args(
        [
            "evaluate",
            "--task",
            "task",
            "--candidate",
            "candidate",
            "--runner",
            "docker",
            "--container-engine",
            "podman",
        ]
    )
    assert args.container_engine == "podman"
