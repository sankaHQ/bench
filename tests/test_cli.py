from __future__ import annotations

from pathlib import Path

from sanka_bench.cli import main


def test_validate_command(repository_root: Path) -> None:
    assert main(["validate", "--root", str(repository_root)]) == 0
