from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from sanka_bench.schema import SchemaError, load_and_validate, validate_payload


def test_native_witness_pc_supports_both_linux_architectures() -> None:
    from sanka_bench.go_guard import witness_pc

    assert witness_pc("  0x412345  0f05  SYSCALL", "amd64") == 0x412347
    assert witness_pc("  0x412340  d4000001  SVC $0", "arm64") == 0x412344
    for code, architecture in (("", "arm64"), ("0x1234 0f05 SYSCALL", "arm64")):
        with pytest.raises(ValueError, match="witness syscall"):
            witness_pc(code, architecture)


def test_go_agent_only_campaign_is_supported() -> None:
    from sanka_bench.go_lane import TASKS, validate_campaign

    validate_campaign(
        {"suite": {"tasks": list(TASKS)}, "execution": {"configurations": ["alone"], "samples": 1}},
        execution=False,
    )


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
    split = trusted.replace(
        f") = {len(marker) + 1}",
        " <unfinished ...>\n1 [0000000000412345] <... write resumed>) = " + str(len(marker) + 1),
    )
    assert dispatch_witness(split, response, {"pc": 0x412345})
    assert not dispatch_witness(split.replace("\n1 [", "\n2 ["), response, {"pc": 0x412345})
    assert not dispatch_witness(
        split.replace("\n1 [0000000000412345]", "\n1 [0000000000500000]"),
        response,
        {"pc": 0x412345},
    )


def test_go_freeze_promotes_module_without_python_entrypoint(tmp_path: Path) -> None:
    from sanka_bench.go_lane import promote

    generated = tmp_path / ".sanka/extensions/sanka/python-to-golang/golang"
    (generated / "cmd/api").mkdir(parents=True)
    (generated / "go.mod").write_text("module example.test/backend\n")
    (generated / "go.sum").write_text("locked\n")
    (generated / "backend.go").write_text("package backend\n")
    (generated / "contract.json").write_text('{"routes": [{"path": "/widgets/"}]}')
    (generated / "cmd/api/main.go").write_text("package main\n")
    promoted = promote(tmp_path)
    assert "go.mod" in promoted and "cmd/api/main.go" in promoted
    assert json.loads((tmp_path / "contract.json").read_text())["routes"] == [{"path": "/widgets/"}]
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


def test_go_extension_lock_requires_the_exact_release() -> None:
    from sanka_bench.go_lane import EXTENSION, release_pins, validate_extension_lock

    pins = release_pins()
    record = {
        "id": EXTENSION,
        "version": pins["extension_version"],
        "snapshot_digest": pins["marketplace_commit"],
        "manifest_digest": pins["manifest_digest"],
        "enabled": True,
    }
    validate_extension_lock(record, pins["marketplace_commit"])
    for key in record:
        changed = {**record, key: None}
        with pytest.raises(ValueError, match="extension lock"):
            validate_extension_lock(changed, pins["marketplace_commit"])
    with pytest.raises(ValueError, match="extension lock"):
        validate_extension_lock(record, "f" * 40)


def test_go_template_pins_releases_but_keeps_execution_disabled(repository_root: Path) -> None:
    from sanka_bench.go_lane import release_pins, validate_campaign

    manifest = json.loads(
        (repository_root / "campaigns/python-go/run-manifest.template.json").read_text()
    )
    for key in ("sanka_cli", "extension_version", "marketplace_commit"):
        assert manifest["toolchain"][key] == release_pins()[key]
    assert manifest["authorization"]["paid_run_authorized"] is False
    assert manifest["models"] == []
    validate_campaign(manifest, execution=False)
    with pytest.raises(ValueError, match="qualification"):
        validate_campaign(manifest, execution=True)


def test_go_multi_request_evidence_preserves_earlier_violations() -> None:
    from jsonschema import Draft202012Validator

    from sanka_bench.go_driver import merge_native
    from sanka_bench.schema import load_schema

    good = {
        "app_is_fiber": True,
        "fiber_dispatch_observed": True,
        "endpoint_in_workspace": True,
        "binary_sha256": "a" * 64,
        "forbidden_imports": [],
        "process_events": [],
        "socket_events": [],
    }
    bad = dict(good, fiber_dispatch_observed=False, process_events=["attempt"])
    merged = merge_native([bad, good])
    assert merged["fiber_dispatch_observed"] is False
    assert merged["process_events"] == ["attempt"]
    schema = load_schema("result")["$defs"]["goNativeEvidence"]
    assert not list(Draft202012Validator(schema).iter_errors(merged))


def test_go_trace_accepts_split_target_exec_but_keeps_delegation_guard() -> None:
    from sanka_bench.go_guard import trace_violations

    start = '12 [aaaa] execve("/target", ["/target"], 0x0 <unfinished ...>\n'
    resume = "12 [bbbb] <... execve resumed>) = 0\n"
    trace = start + "13 [cccc] wait4(12,  <unfinished ...>\n" + resume
    assert trace_violations(trace) == ([], [])
    for invalid in [
        start,
        resume,
        start + resume.replace("12 [", "14 ["),
        start + resume.replace("= 0", "= -1 ENOENT"),
        start.replace("/target", "/other") + resume,
        start + resume.replace("= 0", "= -1 ENOENT") + resume,
        "12 [aaaa] write(1, 'execve(\"/target\", ...) = 0', 30) = 0\n",
    ]:
        assert trace_violations(invalid)[0] == ["target execution was not observed"]
    assert trace_violations(trace + "12 clone(flags=CLONE_VM|CLONE_THREAD) = 15\n") == ([], [])
    assert trace_violations(trace + '12 execve("/target", [], []) = -1 EPERM\n')[0]
    assert trace_violations(trace + "12 fork( <unfinished ...>\n")[0]
    assert trace_violations(trace + "12 connect(3, {}, 16 <unfinished ...>\n")[1]
