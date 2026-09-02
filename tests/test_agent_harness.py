from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture(scope="module")
def harness() -> object:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "run_agent_candidate", SCRIPTS / "run_agent_candidate.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_overlay_exclusions(harness: object) -> None:
    excluded = harness._excluded  # type: ignore[attr-defined]
    assert excluded(Path("public-tests/scenarios.json"))
    assert excluded(Path(".sanka/scan.json"))
    assert excluded(Path("bench-candidate/overlay/target_app.py"))
    assert excluded(Path("__pycache__/x.pyc"))
    assert excluded(Path("db.sqlite3"))
    assert excluded(Path("CLAUDE.md"))
    assert not excluded(Path("target_app.py"))
    assert not excluded(Path("serving_settings.py"))


def test_agent_stats_parses_last_json_line(harness: object) -> None:
    stats_of = harness._agent_stats  # type: ignore[attr-defined]
    payload = json.dumps(
        {
            "num_turns": 12,
            "duration_ms": 61000,
            "total_cost_usd": 1.25,
            "is_error": False,
            "subtype": "success",
            "result": "done",
        }
    )
    stats = stats_of(f"noise\n{payload}\n")
    assert stats["num_turns"] == 12
    assert stats["is_error"] is False
    assert stats_of("no json here") == {}


def test_prompts_differ_only_by_the_sanka_paragraph(harness: object) -> None:
    core = harness.PROMPT_CORE  # type: ignore[attr-defined]
    extra = harness.PROMPT_SANKA  # type: ignore[attr-defined]
    assert "Add new files only" in core
    assert "target_app.py" in core
    assert "rest_framework" in core
    assert "must not import" in core
    # the grading basis is disclosed: a hidden superset extends the public sample
    assert "hidden superset" in core
    assert "representative sample" in core
    assert "FastAPI `APIRoute`" in core
    assert "raw Starlette `Route`" in core
    # the +Sanka variant is strictly additive: same contract, one extra tool
    assert "scan" in extra and "plan --to fastapi" in extra and "bench-candidate" in extra
    # readiness-aware availability, not a copy mandate: the agent is told to read
    # the readiness report and treat low-readiness output as reference material,
    # with the source application staying the specification
    assert "readiness" in extra
    assert "reference material" in extra
    assert "remains the specification" in extra
    assert "cp -R" not in extra
    assert "contract" not in extra.lower()


def test_candidate_modes_preserve_official_arms_and_add_diagnostic_arm(
    harness: object,
) -> None:
    mode = harness._candidate_mode  # type: ignore[attr-defined]
    assert mode("opus-alone") == "alone"
    assert mode("opus-with-sanka") == "with-sanka"
    assert mode("opus-with-sanka-readiness-aware") == "readiness-aware"
    assert mode("opus-experimental") is None


def test_readiness_context_abstains_and_renders_route_checklist(harness: object) -> None:
    context = harness._readiness_context(  # type: ignore[attr-defined]
        {
            "readiness": 0.034,
            "native_routes": 1,
            "native_eligible_routes": 29,
            "needs_adaptation_routes": 1,
            "plan_hash": "sha256:task008",
            "routes": [
                {
                    "automatic": False,
                    "method": "GET",
                    "path": "/api/dynamic/entries/{code}/",
                    "operation": "get",
                    "strategy": "needs-manual-adaptation",
                    "adaptation_reasons": [
                        {
                            "code": "SANKA_DRF_ROUTE_PATTERN_UNSUPPORTED",
                            "feature": "route-pattern",
                            "message": "Regex route requires manual adaptation.",
                        }
                    ],
                },
                {
                    "automatic": True,
                    "method": "GET",
                    "path": "/api/",
                    "operation": "get",
                    "strategy": "native-fastapi-api-root",
                    "adaptation_reasons": [],
                },
            ],
        },
        0.5,
        {
            "skipped_routes": [
                {
                    "pattern": "api/class/entries/",
                    "view": "legacy_project.urls.permanent_style_redirect",
                    "reason": "non-drf-view",
                }
            ]
        },
    )
    assert context["decision"] == "gap-report-only"
    assert len(context["unsupported_routes"]) == 1
    prompt = harness._readiness_prompt(context)  # type: ignore[attr-defined]
    assert "3.4% (1/29" in prompt
    assert "did not generate a scaffold" in prompt
    assert "Do not run `sanka apply`" in prompt
    assert "SANKA_DRF_ROUTE_PATTERN_UNSUPPORTED" in prompt
    assert "api/class/entries/ -> legacy_project.urls.permanent_style_redirect" in prompt
    assert "Allow, Location, and WWW-Authenticate" in prompt
    assert prompt.count("GET /api/dynamic/entries/{code}/") == 1


def test_readiness_context_emits_scaffold_at_threshold(harness: object) -> None:
    context = harness._readiness_context(  # type: ignore[attr-defined]
        {
            "readiness": 0.75,
            "native_routes": 3,
            "native_eligible_routes": 4,
            "needs_adaptation_routes": 1,
            "plan_hash": "sha256:ready",
            "routes": [],
        },
        0.5,
    )
    assert context["decision"] == "emit-scaffold"
    prompt = harness._readiness_prompt(context)  # type: ignore[attr-defined]
    assert "generated `bench-candidate/overlay/`" in prompt


@pytest.mark.parametrize(
    ("readiness", "expected_decision", "expects_apply"),
    [(0.034, "gap-report-only", False), (0.75, "emit-scaffold", True)],
)
def test_readiness_preflight_mechanically_gates_scaffold(
    harness: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    readiness: float,
    expected_decision: str,
    expects_apply: bool,
) -> None:
    plan_dir = tmp_path / ".sanka"
    plan_dir.mkdir()
    (plan_dir / "plan-fastapi.json").write_text(
        json.dumps(
            {
                "readiness": readiness,
                "native_routes": 3 if readiness >= 0.5 else 1,
                "native_eligible_routes": 4 if readiness >= 0.5 else 29,
                "needs_adaptation_routes": 1,
                "plan_hash": "sha256:preflight",
                "routes": [],
            }
        ),
        encoding="utf-8",
    )
    (plan_dir / "scan.json").write_text(
        json.dumps(
            {
                "skipped_routes": [
                    {
                        "pattern": "legacy/redirect/",
                        "view": "config.urls.legacy_redirect",
                        "reason": "non-drf-view",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    commands: list[list[str]] = []

    def fake_run(command: list[str], *, workspace: Path, env: dict[str, str]) -> SimpleNamespace:
        assert workspace == tmp_path
        assert env == {"BENCH": "1"}
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(harness, "_run_sanka_command", fake_run)
    context = harness._prepare_readiness_context(  # type: ignore[attr-defined]
        tmp_path,
        Path("/tools/sanka"),
        {"BENCH": "1"},
        0.5,
    )
    assert context["decision"] == expected_decision
    assert context["skipped_routes"] == [
        {
            "pattern": "legacy/redirect/",
            "view": "config.urls.legacy_redirect",
            "reason": "non-drf-view",
        }
    ]
    assert [command[1] for command in commands] == [
        "scan",
        "plan",
        *(("apply",) if expects_apply else ()),
    ]
    if expects_apply:
        assert "--plan-hash" in commands[-1]
        assert "sha256:preflight" in commands[-1]


def test_as_text_normalizes_timeout_output(harness: object) -> None:
    as_text = harness._as_text  # type: ignore[attr-defined]
    assert as_text(None) == ""
    assert as_text(b"partial \xff output") == "partial � output"
    assert as_text("already text") == "already text"


def test_sanka_runtime_env_adds_fixture_packages_without_mutating_input(
    harness: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        harness.sys,  # type: ignore[attr-defined]
        "path",
        ["/bench/repo", "/bench/.venv/lib/python3.14/site-packages"],
    )
    original = {"PYTHONPATH": "/existing/packages", "BENCH": "1"}
    result = harness._sanka_runtime_env(original)  # type: ignore[attr-defined]
    assert original == {"PYTHONPATH": "/existing/packages", "BENCH": "1"}
    assert result["PYTHONPATH"].split(harness.os.pathsep) == [  # type: ignore[attr-defined]
        "/bench/.venv/lib/python3.14/site-packages",
    ]


def test_codex_command_uses_responses_and_custom_openai_provider(
    harness: object, tmp_path: Path
) -> None:
    command = harness._codex_command(  # type: ignore[attr-defined]
        SimpleNamespace(
            agent_bin="codex",
            model="gpt-test",
            provider="openai",
            provider_variant="serverless-standard",
        ),
        "migrate it",
        tmp_path,
    )
    config = (tmp_path / "config.toml").read_text(encoding="utf-8")
    assert 'wire_api = "responses"' in config
    assert "[model_providers.openai-custom]" in config
    assert 'env_key = "OPENAI_API_KEY"' in config
    assert "--json" in command
    assert 'model_provider="openai-custom"' in command
    assert command[-1] == "migrate it"


def test_codex_stats_reads_usage_and_computes_disclosed_cost(harness: object) -> None:
    event = json.dumps(
        {
            "type": "turn.completed",
            "usage": {"input_tokens": 2_000_000, "output_tokens": 500_000},
        }
    )
    stats = harness._codex_stats(  # type: ignore[attr-defined]
        event,
        SimpleNamespace(price_in=1.0, price_out=2.0),
        12_345.0,
    )
    assert stats["num_turns"] == 1
    assert stats["duration_ms"] == 12_345.0
    assert stats["input_tokens"] == 2_000_000
    assert stats["output_tokens"] == 500_000
    assert stats["total_cost_usd"] == 3.0
    assert stats["is_error"] is False
    assert stats["terminal_event"] == "turn.completed"


def test_codex_stats_treats_recovered_stream_error_as_success(harness: object) -> None:
    transcript = "\n".join(
        [
            json.dumps(
                {
                    "type": "error",
                    "message": "Reconnecting... 1/5 (incomplete response)",
                }
            ),
            json.dumps(
                {
                    "type": "turn.completed",
                    "usage": {
                        "input_tokens": 200,
                        "cached_input_tokens": 150,
                        "output_tokens": 25,
                    },
                }
            ),
        ]
    )
    stats = harness._codex_stats(  # type: ignore[attr-defined]
        transcript,
        SimpleNamespace(price_in=None, price_out=None),
        1000.0,
    )
    assert stats["is_error"] is False
    assert stats["terminal_event"] == "turn.completed"
    assert stats["recovered_error_events"] == 1
    assert stats["cached_input_tokens"] == 150


def test_codex_stats_requires_a_terminal_turn_event(harness: object) -> None:
    stats = harness._codex_stats(  # type: ignore[attr-defined]
        json.dumps({"type": "error", "message": "connection closed"}),
        SimpleNamespace(price_in=None, price_out=None),
        1000.0,
    )
    assert stats["is_error"] is True
    assert stats["subtype"] == "codex-no-terminal-event"
    assert stats["terminal_event"] is None


def test_codex_stats_uses_the_final_terminal_turn_event(harness: object) -> None:
    recovered = "\n".join(
        [
            json.dumps({"type": "turn.failed", "error": {"message": "temporary"}}),
            json.dumps({"type": "turn.completed", "usage": {"output_tokens": 10}}),
        ]
    )
    failed = "\n".join(
        [
            json.dumps({"type": "turn.completed", "usage": {"output_tokens": 10}}),
            json.dumps({"type": "turn.failed", "error": {"message": "terminal"}}),
        ]
    )
    args = SimpleNamespace(price_in=None, price_out=None)
    assert harness._codex_stats(recovered, args, 1.0)["is_error"] is False  # type: ignore[attr-defined]
    assert harness._codex_stats(failed, args, 1.0)["is_error"] is True  # type: ignore[attr-defined]


def test_codex_timeout_without_terminal_event_remains_gradable(harness: object) -> None:
    stats = {"is_error": True, "subtype": "codex-no-terminal-event"}
    should_fail = harness._agent_error_is_terminal  # type: ignore[attr-defined]
    assert should_fail(stats, timed_out=True) is False
    assert should_fail(stats, timed_out=False) is True
    assert should_fail({"is_error": True, "subtype": "codex-turn-failed"}, timed_out=True)


def _fake_agent(
    tmp_path: Path,
    *,
    result: dict | None,
    touch: str | None,
    exit_code: int | None = None,
    preamble: list[dict] | None = None,
) -> Path:
    """Emulate the Claude CLI: print stream events then the result, and exit 1
    whenever the result reports ``is_error`` (the real CLI does exactly that on
    ``error_max_turns``). ``result=None`` prints nothing at all."""
    script = tmp_path / "fake-agent"
    if exit_code is None:
        exit_code = 1 if (result or {}).get("is_error") else 0
    lines = [json.dumps(event) for event in (preamble or [])]
    if result is not None:
        lines.append(json.dumps(result))
    prints = "".join(f"printf '%s\\n' '{line}'\n" for line in lines)
    touch_line = f"touch '{touch}'" if touch else ":"
    script.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "--version" ]; then echo fake-agent-1.0; exit 0; fi\n'
        f"printf '%s\\n' \"$@\" > '{tmp_path / 'fake-agent-argv.txt'}'\n"
        f"{touch_line}\n"
        f"{prints}"
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def _run_adapter(task: Path, agent: Path, out: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "run_agent_candidate.py"),
            "--task",
            str(task),
            "--candidate-id",
            "claude-code-fake-alone",
            "--out",
            str(out),
            "--agent-bin",
            str(agent),
            "--max-turns",
            "60",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_turn_budget_exhaustion_freezes_the_workspace(tmp_path: Path) -> None:
    task = Path(__file__).resolve().parents[1] / "tasks" / "drf-fastapi" / "drf-fastapi-001"
    agent = _fake_agent(
        tmp_path,
        result={
            "num_turns": 60,
            "duration_ms": 1000,
            "total_cost_usd": 0.1,
            "is_error": True,
            "subtype": "error_max_turns",
            "result": "max turns reached",
        },
        touch="target_app.py",
    )
    out = tmp_path / "candidate"
    outcome = _run_adapter(task, agent, out)
    # The fake exits 1 like the real CLI does on error_max_turns; the parsed
    # result must still win over the exit code and the workspace must freeze.
    assert outcome.returncode == 0, outcome.stderr
    assert (out / "overlay" / "target_app.py").is_file()
    disclosure = (out / "GENERATED.md").read_text(encoding="utf-8")
    assert "turn budget (60) exhausted" in disclosure
    assert "frozen as-is" in disclosure
    argv = (tmp_path / "fake-agent-argv.txt").read_text(encoding="utf-8").splitlines()
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert "--verbose" in argv


def test_stream_transcript_is_preserved_and_result_is_last_event(tmp_path: Path) -> None:
    task = Path(__file__).resolve().parents[1] / "tasks" / "drf-fastapi" / "drf-fastapi-001"
    preamble = [
        {"type": "system", "subtype": "init", "model": "fake"},
        {"type": "assistant", "message": {"role": "assistant", "content": []}},
        {"type": "user", "message": {"role": "user", "content": []}},
    ]
    result = {
        "type": "result",
        "num_turns": 3,
        "duration_ms": 1000,
        "total_cost_usd": 0.1,
        "is_error": False,
        "subtype": "success",
        "result": "done",
    }
    agent = _fake_agent(tmp_path, result=result, touch="target_app.py", preamble=preamble)
    out = tmp_path / "candidate"
    outcome = _run_adapter(task, agent, out)
    assert outcome.returncode == 0, outcome.stderr
    log_lines = (out / "agent-log.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["type"] for line in log_lines] == [
        "system",
        "assistant",
        "user",
        "result",
    ]
    assert json.loads((out / "agent-result.json").read_text(encoding="utf-8")) == result
    disclosure = (out / "GENERATED.md").read_text(encoding="utf-8")
    assert "completed within budget" in disclosure


def test_unparseable_nonzero_exit_is_an_agent_run_failure(tmp_path: Path) -> None:
    task = Path(__file__).resolve().parents[1] / "tasks" / "drf-fastapi" / "drf-fastapi-001"
    agent = _fake_agent(tmp_path, result=None, touch="target_app.py", exit_code=1)
    out = tmp_path / "candidate"
    outcome = _run_adapter(task, agent, out)
    assert outcome.returncode == 1
    assert "agent run failed" in outcome.stderr
    assert not (out / "overlay").exists()


def test_successful_claude_turn_overrun_is_disclosed(tmp_path: Path) -> None:
    task = Path(__file__).resolve().parents[1] / "tasks" / "drf-fastapi" / "drf-fastapi-001"
    agent = _fake_agent(
        tmp_path,
        result={
            "num_turns": 67,
            "duration_ms": 1000,
            "total_cost_usd": 0.1,
            "is_error": False,
            "subtype": "success",
            "result": "done",
        },
        touch="target_app.py",
    )
    out = tmp_path / "candidate"
    outcome = _run_adapter(task, agent, out)
    assert outcome.returncode == 0, outcome.stderr
    disclosure = (out / "GENERATED.md").read_text(encoding="utf-8")
    assert "successful completion after 67 turns" in disclosure
    assert "exceeding the requested 60-turn limit" in disclosure
    assert "completed within budget" not in disclosure


def test_empty_workspace_exits_with_classification_code(tmp_path: Path) -> None:
    task = Path(__file__).resolve().parents[1] / "tasks" / "drf-fastapi" / "drf-fastapi-001"
    agent = _fake_agent(
        tmp_path,
        result={
            "num_turns": 1,
            "duration_ms": 500,
            "total_cost_usd": 0.0,
            "is_error": False,
            "subtype": "success",
            "result": "done",
        },
        touch=None,
    )
    out = tmp_path / "candidate"
    outcome = _run_adapter(task, agent, out)
    assert outcome.returncode == 3
    assert "refusing to freeze an empty candidate" in outcome.stderr
    assert "infrastructure" in outcome.stderr
    assert not (out / "overlay").exists()


def test_non_budget_agent_error_stays_unfrozen(tmp_path: Path) -> None:
    task = Path(__file__).resolve().parents[1] / "tasks" / "drf-fastapi" / "drf-fastapi-001"
    agent = _fake_agent(
        tmp_path,
        result={
            "num_turns": 1,
            "duration_ms": 500,
            "total_cost_usd": 0.0,
            "is_error": True,
            "subtype": "error_during_execution",
            "result": "provider exploded",
        },
        touch="target_app.py",
    )
    out = tmp_path / "candidate"
    outcome = _run_adapter(task, agent, out)
    assert outcome.returncode == 1
    assert "agent reported an error" in outcome.stderr
    assert not (out / "overlay").exists()
