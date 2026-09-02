from __future__ import annotations

from pathlib import Path

from sanka_bench.workspace_effects import workspace_changes, workspace_snapshot


def _seed(workspace: Path) -> None:
    (workspace / "app").mkdir(parents=True)
    (workspace / "app" / "views.py").write_text("original", encoding="utf-8")
    (workspace / "settings.py").write_text("DEBUG = False", encoding="utf-8")
    (workspace / "__pycache__").mkdir()
    (workspace / "__pycache__" / "views.cpython-312.pyc").write_bytes(b"\x00")


def test_clean_serving_reports_no_changes(tmp_path: Path) -> None:
    _seed(tmp_path)
    before = workspace_snapshot(tmp_path)
    assert workspace_changes(before, workspace_snapshot(tmp_path)) == []


def test_created_modified_and_deleted_files_are_reported_sorted(tmp_path: Path) -> None:
    _seed(tmp_path)
    before = workspace_snapshot(tmp_path)
    (tmp_path / "app" / "views.py").write_text("mutated", encoding="utf-8")
    (tmp_path / "stray.log").write_text("leak", encoding="utf-8")
    (tmp_path / "settings.py").unlink()
    changes = workspace_changes(before, workspace_snapshot(tmp_path))
    assert changes == [
        {"change": "modified", "path": "app/views.py"},
        {"change": "deleted", "path": "settings.py"},
        {"change": "created", "path": "stray.log"},
    ]


def test_bytecode_and_cache_churn_is_not_evidence(tmp_path: Path) -> None:
    _seed(tmp_path)
    before = workspace_snapshot(tmp_path)
    (tmp_path / "__pycache__" / "settings.cpython-312.pyc").write_bytes(b"\x01")
    (tmp_path / "app" / "compiled.pyc").write_bytes(b"\x02")
    (tmp_path / ".DS_Store").write_bytes(b"\x03")
    assert workspace_changes(before, workspace_snapshot(tmp_path)) == []


def test_change_kinds_are_stable_when_content_varies_between_runs(tmp_path: Path) -> None:
    _seed(tmp_path)
    before = workspace_snapshot(tmp_path)
    (tmp_path / "token.txt").write_text("run-one-nonce", encoding="utf-8")
    first = workspace_changes(before, workspace_snapshot(tmp_path))
    (tmp_path / "token.txt").write_text("run-two-nonce", encoding="utf-8")
    second = workspace_changes(before, workspace_snapshot(tmp_path))
    assert first == second == [{"change": "created", "path": "token.txt"}]
