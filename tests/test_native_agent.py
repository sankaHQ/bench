from __future__ import annotations

import json
import subprocess
import urllib.error
from pathlib import Path

import pytest

from sanka_bench import native_agent as native


def response(provider="openai", *, calls=(), status="completed", model="test-model"):
    if provider == "openai":
        return {
            "model": model,
            "status": status,
            "output": [
                {"type": "reasoning", "id": "r1", "summary": [], "encrypted_content": "opaque"},
                *[
                    {
                        "type": "function_call",
                        "call_id": str(i),
                        "name": name,
                        "arguments": json.dumps(args),
                    }
                    for i, (name, args) in enumerate(calls)
                ],
            ],
            "usage": {
                "input_tokens": 100,
                "output_tokens": 20,
                "input_tokens_details": {"cached_tokens": 40},
                "output_tokens_details": {"reasoning_tokens": 5},
            },
        }
    return {
        "model": model,
        "choices": [
            {
                "finish_reason": "tool_calls" if calls else "stop",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "reasoning_content": "thinking",
                    "tool_calls": [
                        {
                            "id": str(i),
                            "type": "function",
                            "function": {"name": name, "arguments": json.dumps(args)},
                        }
                        for i, (name, args) in enumerate(calls)
                    ],
                },
            }
        ],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "prompt_tokens_details": {"cached_tokens": 40},
        },
    }


def runner(tmp_path, *, provider="openai", execute=None, **kwargs):
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    return native.Runner(
        provider=provider,
        model="test-model",
        effort="high",
        key="test-secret",
        prompt="Test task",
        workspace=workspace,
        artifacts=tmp_path / "artifacts",
        execute=execute or (lambda argv, **kw: subprocess.CompletedProcess(argv, 0, "ok", "")),
        promote=lambda: {"target_app.py": "sha256:test"},
        sanka=kwargs.pop("sanka", None),
        target="flask",
        max_turns=kwargs.pop("max_turns", 5),
        wall_seconds=60,
        **kwargs,
    )


@pytest.mark.parametrize(
    "provider,field", [("openai", "max_output_tokens"), ("fireworks", "max_tokens")]
)
def test_output_budget_controls_request_reservation_and_evidence(
    tmp_path, monkeypatch, provider, field
):
    run = runner(
        tmp_path, provider=provider, max_output_tokens=32768, price_in=0, price_out=1, max_cost=0.02
    )
    assert run.payload()[field] == 32768
    monkeypatch.setattr(native, "post", lambda *args: pytest.fail("larger output must be reserved"))
    _, stats = run.run()
    assert stats["result"] == "cost_reservation"
    assert stats["limits"]["max_output_tokens"] == 32768
    assert stats["work"]["provider_api_requests"] == 0
    with pytest.raises(ValueError, match="positive integer"):
        runner(tmp_path, max_output_tokens=0)


def test_context_budget_preserves_long_reasoning_until_explicit_limit(tmp_path, monkeypatch):
    run = runner(tmp_path, max_context_bytes=512000)
    run.history[0]["content"] = "x" * native.MAX_CONTEXT_BYTES
    monkeypatch.setattr(native, "post", lambda *args: {"accepted": True})
    assert run.request() == {"accepted": True}
    run.history[0]["content"] = "x" * 512000
    monkeypatch.setattr(
        native, "post", lambda *args: pytest.fail("context limit must prevent request")
    )
    _, stats = run.run()
    assert stats["result"] == "context_bytes"
    assert stats["limits"]["max_context_bytes"] == 512000


@pytest.mark.parametrize("provider", ["openai", "fireworks"])
def test_direct_loop_preserves_reasoning_tool_results_and_usage(tmp_path, monkeypatch, provider):
    requests = []

    def post(url, key, payload, timeout):
        assert key == "test-secret" and timeout > 0
        requests.append(json.loads(json.dumps(payload)))
        return response(
            provider, calls=[("exec", {"command": "printf ok"})] if len(requests) == 1 else []
        )

    monkeypatch.setattr(native, "post", post)
    run = runner(tmp_path, provider=provider)
    outcome, stats = run.run()
    history = requests[-1]["input" if provider == "openai" else "messages"]
    assert (
        "opaque" in json.dumps(history)
        if provider == "openai"
        else "thinking" in json.dumps(history)
    )
    assert "exit=0" in json.dumps(history)
    assert stats["input_tokens"] == 200 and stats["cache_read_input_tokens"] == 80
    assert stats["total_tokens"] == 240  # cached input is already in input_tokens
    assert stats["work"]["provider_api_requests"] == 2
    assert stats["work"]["tool_calls"] == 1
    assert stats["cost_usd"] is None and not stats["verified"]
    assert "test-secret" not in outcome.stdout
    assert (run.artifacts / "state.json").is_file()


def cli_response(argv, *, ok=True, **data):
    stage = argv[1]
    payload = {"plan_hash": "sha256:reviewed"} if stage == "plan" else {}
    payload.update(data)
    text = f"sanka-compact/v1 {stage} {'success' if ok else 'error'} within_scope\n"
    text += "\n".join(f"{k}={json.dumps(v)}" for k, v in payload.items())
    return subprocess.CompletedProcess(argv, 0 if ok else 1, text.rstrip(), "")


@pytest.mark.parametrize("target", ["fastapi", "flask"])
def test_full_lifecycle_requires_no_model_call_when_verified(tmp_path, monkeypatch, target):
    commands = []

    def execute(argv, **kw):
        commands.append(argv)
        result = cli_response(argv)
        if argv[1] == "verify":
            result.stdout += "\nok=true\nwarnings=[]\n"
        return result

    monkeypatch.setattr(native, "post", lambda *args: pytest.fail("unnecessary model call"))
    run = runner(tmp_path, sanka=Path("/sanka"), execute=execute)
    run.target = target
    _, stats = run.run()
    assert [c[1] for c in commands] == ["scan", "plan", "apply", "test", "verify"]
    assert commands[2][commands[2].index("--plan-hash") + 1] == "sha256:reviewed"
    assert commands[1][commands[1].index("--package-manager") + 1] == "pip"
    assert ("--bench-candidate" in commands[2]) is (target == "fastapi")
    assert "--output" not in commands[3]  # test must use the reviewed output configuration
    assert stats["verified"] and stats["num_turns"] == 0
    assert stats["work"]["commands"] == 5
    assert stats["work"]["tool_calls"] == 0


def test_repair_rechecks_without_regeneration_and_preserves_test_failure(tmp_path, monkeypatch):
    commands = []

    def execute(argv, **kw):
        commands.append(argv)
        if argv[0] == "/bin/sh":
            (tmp_path / "workspace/seed.py").write_text("# seed")
            return subprocess.CompletedProcess(argv, 0, "repaired", "")
        result = cli_response(argv, ok=argv[1] != "test")
        if argv[1] == "verify":
            result.stdout += "\nok=" + ("true" if "--seed" in argv else "false")
        return result

    replies = iter(
        [
            response(calls=[("exec", {"command": "repair"})]),
            response(calls=[("verify", {"seed": "seed.py"})]),
        ]
    )
    monkeypatch.setattr(native, "post", lambda *args: next(replies))
    run = runner(tmp_path, sanka=Path("/sanka"), execute=execute)
    _, stats = run.run()
    assert stats["verified"] and not stats["stages"]["test"]["ok"]
    assert len([c for c in commands if c[1] == "apply"]) == 1
    assert len([c for c in commands if c[1] == "verify"]) == 2
    assert stats["num_turns"] == 2  # no final summary turn


def test_json_seed_is_recoverable_tool_error_before_cli_execution(tmp_path):
    def execute(argv, **kw):
        result = cli_response(argv)
        result.stdout += "\nok=true"
        return result

    run = runner(tmp_path, sanka=Path("sanka"), execute=execute)
    (run.workspace / "seed.json").write_text('[{"deleted": false}]')
    result = run.dispatch({"name": "verify", "arguments": '{"seed":"seed.json"}'})
    assert result.startswith("tool error:") and "Python" in result
    assert not run.events and run.seed is None
    (run.workspace / "seed.py").write_text("# Python seed script")
    result = run.dispatch({"name": "verify", "arguments": '{"seed":"seed.py"}'})
    assert not result.startswith("tool error:")
    assert run.seed == "seed.py"


def test_verify_warning_explains_rejection_and_seeded_tool_rechecks(tmp_path):
    commands = []

    def execute(argv, **kw):
        commands.append(argv)
        result = cli_response(
            argv,
            warnings=[] if "--seed" in argv else ["Authentication coverage missing"],
        )
        result.stdout += "\nok=true\n"
        return result

    run = runner(tmp_path, sanka=Path("/sanka"), execute=execute)
    summary = run.verify(None)
    assert not run.verified
    assert "Harness verification not accepted" in summary
    assert "Authentication coverage missing" in summary
    assert run.verify(None) == summary and len(commands) == 1
    (run.workspace / "seed.py").write_text("# public seed")
    summary = run.dispatch({"name": "verify", "arguments": json.dumps({"seed": "seed.py"})})
    assert run.verified and len(commands) == 2
    assert "Harness verification not accepted" not in summary


@pytest.mark.parametrize("failure", ["incomplete", "wrong-model", "missing-usage", "bad-arguments"])
def test_invalid_response_never_executes_tools(tmp_path, monkeypatch, failure):
    value = response(calls=[("exec", {"command": "danger"})])
    if failure == "incomplete":
        value["status"] = "incomplete"
    elif failure == "wrong-model":
        value["model"] = "another-model"
    elif failure == "missing-usage":
        value["usage"] = {}
    else:
        value["output"][-1]["arguments"] = '{"command":'
    monkeypatch.setattr(native, "post", lambda *args: value)
    run = runner(tmp_path, max_turns=1, execute=lambda *args, **kw: pytest.fail("must not execute"))
    _, stats = run.run()
    assert not stats["verified"]
    assert stats["work"]["commands"] == 0
    if failure == "missing-usage":
        assert stats["total_tokens"] is None


def test_rate_limit_retries_without_replaying_tools(tmp_path, monkeypatch):
    count = 0

    def post(*args):
        nonlocal count
        count += 1
        if count == 1:
            raise urllib.error.HTTPError("url", 429, "limited", {}, None)
        return response()

    monkeypatch.setattr(native, "post", post)
    monkeypatch.setattr(native.time, "sleep", lambda _: None)
    _, stats = runner(tmp_path).run()
    assert stats["work"]["provider_retries"] == 1
    assert stats["work"]["provider_api_requests"] == 2
    assert stats["num_turns"] == 1


@pytest.mark.parametrize("limit", ["cost", "context", "tools"])
def test_budget_stops_preserve_state(tmp_path, monkeypatch, limit):
    run = runner(
        tmp_path,
        max_turns=1,
        price_in=1,
        price_out=1,
        max_cost=0.00001 if limit == "cost" else None,
    )
    if limit == "context":
        run.history[0]["content"] = "x" * native.MAX_CONTEXT_BYTES
    if limit == "tools":
        monkeypatch.setattr(
            native,
            "post",
            lambda *args: response(
                calls=[("exec", {"command": "one"}), ("exec", {"command": "two"})]
            ),
        )
    else:
        monkeypatch.setattr(
            native, "post", lambda *args: pytest.fail("budget must prevent request")
        )
    _, stats = run.run()
    assert stats["work"]["commands"] == (1 if limit == "tools" else 0)
    assert (run.artifacts / "state.json").is_file()
    assert not stats["is_error"] and not stats["verified"]


def test_full_tool_output_survives_context_truncation(tmp_path):
    raw = "start" + "x" * 9000 + "end"
    run = runner(tmp_path, execute=lambda argv, **kw: subprocess.CompletedProcess(argv, 0, raw, ""))
    _, summary = run.command(["test"])
    assert "[truncated]" in summary and "start" in summary and "end" in summary
    assert (run.artifacts / "tools/0001.txt").read_text() == raw
    assert len(summary) < len(raw)


@pytest.mark.parametrize("deadline_expired", [False, True])
def test_timeout_preserves_billing_and_classifies_deadline(tmp_path, monkeypatch, deadline_expired):
    run = runner(tmp_path, price_in=1, price_out=1)

    def post(*args):
        if deadline_expired:
            run.deadline = 0
        raise TimeoutError("response lost")

    monkeypatch.setattr(native, "post", post)
    outcome, stats = run.run()
    assert stats["is_error"] is not deadline_expired
    assert outcome.returncode == (0 if deadline_expired else 1)
    assert stats["result"] == (
        "wall_clock" if deadline_expired else "provider_or_runner_error:TimeoutError"
    )
    assert stats["cost_usd"] is None and stats["total_tokens"] is None
    assert stats["work"]["provider_api_requests"] == 1
    assert stats["work"]["provider_retries"] == 0


def test_repeated_verification_uses_result_until_command_invalidates_it(tmp_path):
    def execute(argv, **kw):
        result = cli_response(argv)
        result.stdout += "\nok=false\n"
        return result

    run = runner(tmp_path, sanka=Path("/sanka"), execute=execute)
    run.verify(None)
    run.verify(None)
    assert run.commands == 1
    run.dispatch({"name": "exec", "arguments": '{"command":"inspect"}'})
    run.verify(None)
    assert run.commands == 3


def test_interruption_keeps_checkpoint_and_stops(tmp_path, monkeypatch):
    def post(*args):
        raise KeyboardInterrupt

    monkeypatch.setattr(native, "post", post)
    run = runner(tmp_path)
    with pytest.raises(KeyboardInterrupt):
        run.run()
    assert (run.artifacts / "state.json").is_file()
    stats = json.loads((run.artifacts / "state.json").read_text())["stats"]
    assert stats["result"] == "interrupted" and stats["total_tokens"] is None


def test_qualification_records_real_sandbox_tool_roundtrip(tmp_path, monkeypatch):
    import importlib.util
    import sys

    path = Path(__file__).resolve().parents[1] / "scripts/qualify_native_route.py"
    spec = importlib.util.spec_from_file_location("qualify_native_route", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    out = tmp_path / "qualification.json"
    monkeypatch.setenv("OPENAI_API_KEY", "fake-test-key")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "qualify_native_route",
            "--provider",
            "openai",
            "--model",
            "test-model",
            "--out",
            str(out),
        ],
    )
    calls = 0

    def post(url, key, payload, timeout):
        nonlocal calls
        calls += 1
        nonce = payload["input"][0]["content"].split("exactly ")[1].split()[0]
        return response(
            calls=[("exec", {"command": f"printf {nonce} > probe.txt"})] if calls == 1 else []
        )

    monkeypatch.setattr(native, "post", post)
    assert module.main() == 0
    evidence = json.loads(out.read_text())
    assert evidence["status"] == "qualified" and all(evidence["checks"].values())
    assert evidence["native"]["version"] == native.version()
    assert out.with_suffix(".jsonl").is_file()


def test_command_timing_distinguishes_timeout_from_exit_124(tmp_path):
    def timeout(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 1, output="partial")

    run = runner(tmp_path, execute=timeout)
    run.command(["test"], phase="verify")
    end = run.events[-1]
    assert end["timed_out"] is True
    assert end["phase"] == "verify"
    assert end["duration_seconds"] >= 0
    assert end["elapsed_seconds"] >= run.events[-2]["elapsed_seconds"]
    run.execute = lambda argv, **kw: subprocess.CompletedProcess(argv, 124, "", "")
    run.command(["test"])
    assert run.events[-1]["timed_out"] is False


def test_unchanged_failed_finalization_stops_without_third_paid_response(tmp_path, monkeypatch):
    run = runner(tmp_path, sanka=Path("sanka"))
    monkeypatch.setattr(run, "bootstrap", lambda: "coverage missing")
    monkeypatch.setattr(run, "verify", lambda seed: "coverage missing")
    requests = []

    def request():
        requests.append(1)
        return response()

    monkeypatch.setattr(run, "request", request)
    _, stats = run.run()
    assert stats["result"] == "verification_failed"
    assert len(requests) == 2


def test_bounded_read_preserves_verification_and_rejects_escape(tmp_path):
    run = runner(tmp_path)
    (run.workspace / "notes").write_text("first\nsecond\nthird\n")
    run.verified = True

    def read(path, start=2, lines=1):
        return run.dispatch(
            {
                "name": "read",
                "arguments": json.dumps({"path": path, "start": start, "lines": lines}),
            }
        )

    assert read("notes") == "2: second\n"
    assert run.verified
    output = run.artifacts / "tools" / "saved.txt"
    output.write_text("saved\n")
    assert read(str(output), start=1) == "1: saved\n"
    run.max_turns = 10
    outside = tmp_path / "outside"
    outside.write_text("private")
    (run.workspace / "escape").symlink_to(outside)
    assert read("escape").startswith("tool error:")
    assert read("notes", lines=201).startswith("tool error:")
    assert read("notes", start=True).startswith("tool error:")


@pytest.mark.parametrize(
    "data,category",
    [
        ({"ok": False, "summary": {"status_mismatches": 1}}, "candidate_failure"),
        ({"ok": True, "warnings": ["seed missing"]}, "coverage_incomplete"),
        ({"ok": False, "summary": {"source_expectation_mismatches": 1}}, "coverage_incomplete"),
        ({"ok": True, "warnings": []}, None),
    ],
)
def test_verification_failure_categories(tmp_path, data, category):
    run = runner(tmp_path, sanka=Path("sanka"))

    def execute(argv, **kw):
        result = cli_response(argv)
        result.stdout += "\n" + "\n".join(f"{k}={json.dumps(v)}" for k, v in data.items())
        return result

    run.execute = execute
    run.verify(None)
    assert run.stages["verify"]["failure_category"] == category
    assert run.verified is (category is None)


@pytest.mark.parametrize("details", [None, {}, {"schema": "sanka-verify-replay/v1", "ok": True}])
def test_invalid_replay_error_still_stops_as_infrastructure(tmp_path, details):
    error = {"code": "SANKA_EXTENSION_REPLAY_MISMATCH", "details": details}
    run = runner(
        tmp_path,
        sanka=Path("sanka"),
        execute=lambda argv, **kw: subprocess.CompletedProcess(
            argv, 1, "sanka-compact/v1 verify error failed\nerror=" + json.dumps(error), ""
        ),
    )
    with pytest.raises(RuntimeError, match="lifecycle protocol"):
        run.verify(None)
    assert run.stages["verify"]["failure_category"] == "infrastructure_failure"


def test_verification_timeout_is_infrastructure_failure(tmp_path):
    def timeout(argv, **kw):
        raise subprocess.TimeoutExpired(argv, 1, output="partial report")

    run = runner(tmp_path, sanka=Path("sanka"), execute=timeout)
    with pytest.raises(RuntimeError, match="lifecycle protocol"):
        run.verify(None)
    assert run.stages["verify"]["failure_category"] == "infrastructure_failure"
    assert run.events[-2]["timed_out"]


@pytest.mark.parametrize("source_only", [False, True])
def test_cli_replay_error_details_reach_verification_handoff(tmp_path, source_only):
    details = {
        "schema": "sanka-verify-replay/v1",
        "ok": False,
        "summary": {"source_expectation_mismatches" if source_only else "status_mismatches": 1},
        "failures": [{"id": "probe", "message": "status mismatch"}],
        "coverage_issues": [{"code": "authentication_coverage", "scenario_ids": ["probe"]}],
    }
    error = {"code": "SANKA_EXTENSION_REPLAY_MISMATCH", "details": details}

    def execute(argv, **kw):
        return subprocess.CompletedProcess(
            argv, 1, "sanka-compact/v1 verify error failed\nerror=" + json.dumps(error), ""
        )

    run = runner(tmp_path, sanka=Path("sanka"), execute=execute)
    summary = run.verify(None)
    stage = run.stages["verify"]
    assert stage["failure_category"] == (
        "coverage_incomplete" if source_only else "candidate_failure"
    )
    assert stage["data"]["failures"] == details["failures"]
    assert "status mismatch" in summary
    assert not run.verified


def test_provider_phase_and_usage_are_recorded(tmp_path, monkeypatch):
    run = runner(tmp_path)
    monkeypatch.setattr(native, "post", lambda *args: response())
    _, stats = run.run()
    assert stats["usage_complete"]
    assert stats["phase_seconds"]["provider"] >= 0
    assert [e["status"] for e in run.events if e["type"] == "request_end"] == ["received"]


@pytest.mark.parametrize("final_tool", [False, True])
def test_same_verification_after_exec_stops_despite_new_artifact_path(
    tmp_path, monkeypatch, final_tool
):
    def execute(argv, **kw):
        if argv[0] == "/bin/sh":
            return subprocess.CompletedProcess(argv, 0, "", "")
        result = cli_response(argv)
        if argv[1] == "verify":
            result.stdout += '\nok=false\nsummary={"status_mismatches":1}\n'
        return result

    finish = response(calls=[("verify", {"seed": None})]) if final_tool else response()
    replies = iter([finish, response(calls=[("exec", {"command": "true"})]), finish])
    monkeypatch.setattr(native, "post", lambda *args: next(replies))
    run = runner(tmp_path, sanka=Path("sanka"), execute=execute)
    _, stats = run.run()
    assert stats["result"] == "verification_failed"
    assert stats["num_turns"] == 3
    assert stats["failure_category"] == "candidate_failure"


def test_read_enforces_deadline_while_skipping_lines(tmp_path, monkeypatch):
    run = runner(tmp_path)
    (run.workspace / "many").write_text("x\n" * 100)
    checks = []

    def remaining():
        checks.append(1)
        if len(checks) == 3:
            raise native.BudgetReached("wall_clock")
        return 1

    monkeypatch.setattr(run, "remaining", remaining)
    with pytest.raises(native.BudgetReached, match="wall_clock"):
        run.dispatch(
            {"name": "read", "arguments": json.dumps({"path": "many", "start": 90, "lines": 1})}
        )
    assert len(checks) == 3


def test_model_verifier_protocol_failure_stops_as_infrastructure(tmp_path, monkeypatch):
    run = runner(tmp_path, sanka=Path("sanka"))
    monkeypatch.setattr(run, "bootstrap", lambda: "existing scaffold")
    monkeypatch.setattr(native, "post", lambda *args: response(calls=[("verify", {"seed": None})]))
    _, stats = run.run()
    assert stats["is_error"]
    assert stats["failure_category"] == "infrastructure_failure"
    assert stats["num_turns"] == 1
