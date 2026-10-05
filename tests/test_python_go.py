from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from sanka_bench.schema import SchemaError, load_and_validate, validate_payload


def test_go_contract_rejects_python_target_and_escaping_entrypoint(repository_root: Path) -> None:
    path = repository_root / "tasks/python-go/python-go-001/task.yaml"
    task = load_and_validate(path, "task")
    for change in ({"framework": "fastapi"}, {"entrypoint": "../main.go"}):
        invalid = copy.deepcopy(task)
        invalid["target"].update(change)
        with pytest.raises(SchemaError):
            validate_payload(invalid, "task", label="invalid Go task")


def test_go_campaign_rejects_historical_tasks_and_unqualified_execution() -> None:
    from sanka_bench.go_lane import validate_campaign

    manifest = {
        "suite": {"tasks": [f"python-go-{index:03d}" for index in range(1, 5)]},
        "execution": {"configurations": ["alone", "sanka-cli"], "samples": 1},
    }
    validate_campaign(manifest, execution=False)
    with pytest.raises(ValueError, match="qualification"):
        validate_campaign(manifest, execution=True)
    manifest["suite"]["tasks"].append("drf-fastapi-001")
    with pytest.raises(ValueError, match="exactly"):
        validate_campaign(manifest, execution=False)


def test_go_trace_rejects_delegation_and_outbound_network() -> None:
    from sanka_bench.go_guard import trace_violations

    trace = '1 execve("/target", ["/target"], []) = 0\n'
    assert trace_violations(trace) == ([], [])
    processes, sockets = trace_violations(
        trace
        + '2 execve("/python", [], []) = -1 EPERM\n'
        + "2 connect(3, {sa_family=AF_INET}, 16) = -1 ENETUNREACH\n"
    )
    assert processes and sockets


def test_dispatch_witness_rejects_candidate_stdout_and_duplicate_witnesses() -> None:
    import hashlib

    from sanka_bench.go_guard import dispatch_witness

    response = '{"status":200,"body":null}'
    marker = "SANKA_BENCH_ATTEST=" + hashlib.sha256(response.encode()).hexdigest()
    write = f'write(1, "{marker}\\n", {len(marker) + 1}) = {len(marker) + 1}\n'
    trusted = "1 [0000000000412345] " + write
    forged = "1 [0000000000500000] " + write
    assert dispatch_witness(trusted, response, {"pc": 0x412345})
    assert not dispatch_witness(forged, response, {"pc": 0x412345})
    assert not dispatch_witness("", response, {"pc": 0x412345})
    assert not dispatch_witness(trusted * 2, response, {"pc": 0x412345})


def test_go_freeze_promotes_module_without_python_entrypoint(tmp_path: Path) -> None:
    from sanka_bench.go_lane import promote

    generated = tmp_path / ".sanka/extensions/sanka/python-to-golang/golang"
    (generated / "cmd/api").mkdir(parents=True)
    (generated / "go.mod").write_text("module example.test/backend\n")
    (generated / "go.sum").write_text("locked\n")
    (generated / "backend.go").write_text("package backend\n")
    (generated / "cmd/api/main.go").write_text("package main\n")
    promoted = promote(tmp_path)
    assert "go.mod" in promoted and "cmd/api/main.go" in promoted
    assert (tmp_path / "bench_adapter.go").is_file()
    assert not (tmp_path / "target_app.py").exists()


def test_go_scenario_copies_preserve_pinned_bytes(repository_root: Path) -> None:
    for path in (repository_root / "tasks/python-go").glob("*/task.draft.json"):
        draft = json.loads(path.read_text())
        for kind, reference in draft["scenarios"].items():
            actual = path.parent / ("public-tests" if kind == "public" else "evaluation")
            assert (actual / "scenarios.json").read_bytes() == (
                repository_root / reference["path"]
            ).read_bytes()
