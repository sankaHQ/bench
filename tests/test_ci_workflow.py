from __future__ import annotations

from pathlib import Path

import yaml


def test_converter_regression_runs_checked_out_code_without_credentials(
    repository_root: Path,
) -> None:
    """The regression job executes code from a caller-chosen extensions commit, so it
    must not reference secrets or leave the job token in the checked-out repositories."""
    path = repository_root / ".github/workflows/converter-regression.yml"
    source = path.read_text()
    assert "secrets." not in source
    workflow = yaml.load(source, Loader=yaml.BaseLoader)
    checkouts = [
        step["with"]
        for step in workflow["jobs"]["converter"]["steps"]
        if "actions/checkout@" in step.get("uses", "")
    ]
    assert checkouts
    assert all(checkout["persist-credentials"] == "false" for checkout in checkouts)
