from __future__ import annotations

from pathlib import Path

from sanka_bench.hashing import digest_payload, digest_tree


def test_payload_hash_is_canonical() -> None:
    assert digest_payload({"b": 2, "a": 1}) == digest_payload({"a": 1, "b": 2})


def test_tree_hash_excludes_runtime_artifacts(tmp_path: Path) -> None:
    (tmp_path / "source.py").write_text("answer = 42\n", encoding="utf-8")
    original = digest_tree(tmp_path)
    (tmp_path / "state.sqlite3").write_bytes(b"runtime")
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "source.pyc").write_bytes(b"runtime")
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "result.json").write_text("{}\n", encoding="utf-8")
    docker_output = tmp_path / ".sanka-bench-output-test"
    docker_output.mkdir()
    (docker_output / "result.json").write_text("{}\n", encoding="utf-8")
    assert digest_tree(tmp_path) == original
