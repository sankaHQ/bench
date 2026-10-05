"""Check unqualified Go task provenance without executing applications or benchmarks."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from sanka_bench.hashing import digest_tree
from sanka_bench.schema import load_document


def check(root: Path) -> None:
    lane = root / "tasks/python-go"
    drafts = sorted(lane.glob("*/task.draft.json"))
    assert len(drafts) == 4, "expected four draft tasks"
    assert len(list(lane.rglob("task.yaml"))) == 4, "expected four Go manifests"
    for index, draft in enumerate(drafts, start=1):
        task = json.loads(draft.read_text())
        assert task["format"] == "sanka-bench/draft-task/v1", draft
        assert task["status"] == "implemented-unqualified", draft
        assert task["id"] == draft.parent.name == f"python-go-{index:03d}", draft
        assert task["lane"] == "python-go", draft
        assert task["execution"] == {"enabled": False, "paid_run_authorized": False}, draft
        source = task["source"]
        assert re.fullmatch(r"[0-9a-f]{40}", source["commit"]), draft
        origin = (root / source["task"]).resolve()
        assert origin.is_relative_to(root / "tasks"), draft
        original = load_document(origin / "task.yaml")
        source_dir = (root / source["path"]).resolve()
        assert source_dir == origin / original["source"]["path"], draft
        assert digest_tree(origin) == source["task_digest"], draft
        assert digest_tree(source_dir) == source["digest"], draft
        assert digest_tree(draft.parent / "source") == source["digest"], draft
        assert source["digest"] == original["source"]["provenance"]["digest"], draft
        observations = {}
        for kind, reference in task["scenarios"].items():
            path = (root / reference["path"]).resolve()
            relative = (
                "public-tests/scenarios.json"
                if kind == "public"
                else original["evaluation"]["scenarios"]
            )
            assert path == origin / relative, draft
            payload = path.read_bytes()
            assert "sha256:" + hashlib.sha256(payload).hexdigest() == reference["sha256"], path
            copied = draft.parent / ("public-tests" if kind == "public" else "evaluation")
            assert (copied / "scenarios.json").read_bytes() == payload, draft
            scenarios = json.loads(payload)
            assert len(scenarios) == reference["count"], path
            observations[kind] = {scenario["id"]: scenario for scenario in scenarios}
            assert len(observations[kind]) == len(scenarios), path
        assert observations.keys() == {"public", "evaluation"}, draft
        assert all(
            observations["evaluation"].get(key) == value
            for key, value in observations["public"].items()
        ), draft
    print("4 unqualified Go tasks: original provenance and scenario copies intact")


if __name__ == "__main__":
    check(Path(__file__).resolve().parents[1])
