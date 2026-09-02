"""Deterministic content hashing for benchmark provenance."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

_EXCLUDED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".sanka-bench-output-",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "reports",
}
_EXCLUDED_SUFFIXES = {".pyc", ".sqlite3"}


def digest_payload(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def digest_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        relative = path.relative_to(root)
        if any(
            part in _EXCLUDED_PARTS or part.startswith(".sanka-bench-output-")
            for part in relative.parts
        ):
            continue
        if path.suffix in _EXCLUDED_SUFFIXES:
            continue
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"
