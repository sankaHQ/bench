"""Measured workspace side effects for scenario drivers.

Every task driver snapshots the served workspace before its scenario runs and
reports the files the application created, modified, or deleted while serving.
The oracle and the candidate report through the same probe, so the
side-effect-parity gate compares measured evidence instead of a hardcoded
empty list: a candidate that quietly writes files into its workspace now
fails parity even when its HTTP responses match.

Only change kinds enter the evidence — never content digests — so a file
whose contents legitimately differ between clean runs still fingerprints
identically for the determinism gate.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_EXCLUDED_PARTS = {"__pycache__"}
_EXCLUDED_SUFFIXES = {".pyc"}
_EXCLUDED_NAMES = {".DS_Store"}


def workspace_snapshot(workspace: Path) -> dict[str, str]:
    """Map every served file (workspace-relative path) to a content digest."""
    snapshot: dict[str, str] = {}
    for path in sorted(workspace.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(workspace)
        if any(part in _EXCLUDED_PARTS for part in relative.parts):
            continue
        if relative.suffix in _EXCLUDED_SUFFIXES or relative.name in _EXCLUDED_NAMES:
            continue
        snapshot[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


def workspace_changes(before: dict[str, str], after: dict[str, str]) -> list[dict[str, str]]:
    """Deterministic, sorted list of files the scenario created/modified/deleted."""
    changes = [{"change": "created", "path": path} for path in after if path not in before]
    changes += [
        {"change": "modified", "path": path}
        for path, digest in after.items()
        if path in before and before[path] != digest
    ]
    changes += [{"change": "deleted", "path": path} for path in before if path not in after]
    return sorted(changes, key=lambda change: change["path"])
