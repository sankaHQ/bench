"""Check the published snapshot against its original sources and selected cells."""

import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1] / "results" / "2026-09-12"
data = json.loads((root / "latest-2026-09-12.json").read_text())
assert data["metadata"]["sourceHashes"] == [
    hashlib.sha256((root / name).read_bytes()).hexdigest() for name in data["metadata"]["sources"]
]
primary = data["cells"] + data["claude"]["cells"]


def identity(cell):
    return cell["model"], cell["task"], cell["config"]


keys = {identity(c) for c in primary}
cells = primary + [
    c for c in data["sonnet"]["cells"] if c["passed"] is not None and identity(c) not in keys
]
assert len(cells) == len({identity(c) for c in cells}) == 272
assert len(data["allRuns"]["summary"]) == 16
for row in data["allRuns"]["summary"]:
    group = [c for c in cells if c["model"] == row["modelId"] and c["config"] == row["config"]]
    assert len(group) == row["tasksTotal"] == 17
    assert {c["task"] for c in group} == set(data["tasks"])
    assert row["tasksPassed"] == sum(c["passed"] for c in group)
    assert abs(row["scorePercent"] - 100 * row["tasksPassed"] / 17) < 1e-9
    for metric in ("input", "output", "cached", "cost"):
        assert abs(row[metric]["value"] - sum(c[metric]["value"] or 0 for c in group)) < 1e-6
        assert row[metric]["complete"] == all(c[metric]["complete"] for c in group)
    assert abs(row["durationSeconds"] - sum(c["seconds"] or 0 for c in group)) < 1e-6
    for metric in ("commands", "toolCalls"):
        assert row[metric] == sum(c[metric] or 0 for c in group)
print("Published results verified: 8 models, 17 tasks, 272 cells; scores and metrics agree.")
