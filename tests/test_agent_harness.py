from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from sanka_bench.environment import isolated_environment
from sanka_bench.schema import load_and_validate

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def test_isolated_environment_drops_host_secrets_and_global_tool_path() -> None:
    source = {
        "HOME": "/Users/bench",
        "PATH": "/opt/homebrew/bin:/bin",
        "AWS_SECRET_ACCESS_KEY": "secret",
        "ANTHROPIC_AUTH_TOKEN": "gateway-secret",
    }

    assert isolated_environment(source) == {
        "HOME": "/Users/bench",
        "PATH": os.defpath,
    }
    assert isolated_environment(source, {"ANTHROPIC_AUTH_TOKEN"}) == {
        "HOME": "/Users/bench",
        "PATH": os.defpath,
        "ANTHROPIC_AUTH_TOKEN": "gateway-secret",
    }


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


def test_subscription_stats_keep_tokens_without_claiming_actual_cost(harness: object) -> None:
    stdout = json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "num_turns": 3,
            "duration_ms": 1200,
            "total_cost_usd": 1.25,
            "is_error": False,
            "modelUsage": {
                "gateway-alias": {
                    "inputTokens": 100,
                    "cacheCreationInputTokens": 20,
                    "cacheReadInputTokens": 40,
                    "outputTokens": 30,
                }
            },
        }
    )

    stats = harness.claude_stats(  # type: ignore[attr-defined]
        stdout,
        billing_mode="subscription",
        requested_model_id="gateway-alias",
        actual_model_id="claude-sonnet-5",
        measured_ms=1300,
    )

    assert stats["cost_usd"] is None
    assert stats["reported_equivalent_cost_usd"] == 1.25
    assert stats["cost_basis"] == "subscription-no-marginal-cost"
    assert stats["input_tokens"] == 100
    assert stats["cache_creation_input_tokens"] == 20
    assert stats["cache_read_input_tokens"] == 40
    assert stats["output_tokens"] == 30
    assert stats["total_tokens"] == 190
    assert stats["model_usage"]["gateway-alias"]["client_model_id"] == "gateway-alias"


def test_gateway_stats_do_not_claim_claude_estimate_as_actual_cost(harness: object) -> None:
    stats = harness.claude_stats(  # type: ignore[attr-defined]
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "num_turns": 1,
                "total_cost_usd": 0.75,
                "is_error": False,
                "modelUsage": {"gpt-alias": {"inputTokens": 10, "outputTokens": 5}},
            }
        ),
        billing_mode="api_key",
        requested_model_id="gpt-alias",
        actual_model_id="gpt-5.6-20260901",
        measured_ms=900,
    )

    assert stats["cost_usd"] is None
    assert stats["reported_equivalent_cost_usd"] == 0.75
    assert stats["cost_basis"] == "claude-code-reported-equivalent-unverified"
    assert stats["duration_ms"] == 900


def test_claude_stats_leave_missing_usage_null(harness: object) -> None:
    stats = harness.claude_stats(  # type: ignore[attr-defined]
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "num_turns": 1,
                "is_error": False,
            }
        ),
        billing_mode="subscription",
        requested_model_id="claude-sonnet-5",
        actual_model_id="claude-sonnet-5",
        measured_ms=500,
    )

    assert stats["input_tokens"] is None
    assert stats["cache_creation_input_tokens"] is None
    assert stats["cache_read_input_tokens"] is None
    assert stats["output_tokens"] is None
    assert stats["total_tokens"] is None
    assert stats["cost_usd"] is None


def test_claude_stats_do_not_turn_partial_usage_into_zero(harness: object) -> None:
    stats = harness.claude_stats(  # type: ignore[attr-defined]
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "num_turns": 1,
                "is_error": False,
                "modelUsage": {"gateway-alias": {"inputTokens": 10}},
            }
        ),
        billing_mode="api_key",
        requested_model_id="gateway-alias",
        actual_model_id="gpt-5.6-20260901",
        measured_ms=500,
    )

    assert stats["input_tokens"] == 10
    assert stats["cache_creation_input_tokens"] is None
    assert stats["cache_read_input_tokens"] is None
    assert stats["output_tokens"] is None
    assert stats["total_tokens"] is None


def test_sanka_prompt_exposes_cli_with_extension_environment(harness: object) -> None:
    core = harness.PROMPT_CORE  # type: ignore[attr-defined]
    extra = harness.PROMPT_SANKA  # type: ignore[attr-defined]
    assert "Add new files only" in core
    assert "target_app.py" in core
    assert "rest_framework" in core
    assert "must not import" in core
    assert "{grading_scope}" in core
    assert "FastAPI `APIRoute`" in core
    assert "raw Starlette `Route`" in core
    # Both Sanka arms receive the same runtime plumbing. Without this explicit
    # passthrough, the CLI's isolated extension process cannot import the fixture.
    rendered = extra.format(sanka="/tools/sanka")
    assert "Sanka migration CLI" in rendered
    assert "/tools/sanka" in rendered
    assert "--extension-env PYTHONPATH" in rendered
    assert "scan" not in rendered
    assert "plan" not in rendered
    assert "apply" not in rendered


def test_skill_prompt_discloses_project_local_skill_without_usage_guidance(
    harness: object,
) -> None:
    rendered = harness.PROMPT_SANKA_SKILL  # type: ignore[attr-defined]
    assert "project-local" in rendered
    assert "sanka-cli" in rendered
    assert "scan" not in rendered
    assert "plan" not in rendered
    assert "apply" not in rendered


def test_prompt_uses_the_tasks_actual_grading_scope_and_budget(harness: object) -> None:
    tasks = SCRIPTS.parent / "tasks" / "drf-fastapi"
    public = harness.task_prompt(tasks / "drf-fastapi-001", 60, 3600)  # type: ignore[attr-defined]
    hidden = harness.task_prompt(tasks / "drf-fastapi-004", 120, 900)  # type: ignore[attr-defined]
    assert "hidden superset" not in public
    assert "hidden superset" in hidden
    assert "60 tool-use turns" in public
    assert "120 tool-use turns" in hidden
    assert "900 seconds" in hidden


def test_candidate_modes_preserve_official_arms_and_add_diagnostic_arm(
    harness: object,
) -> None:
    mode = harness._candidate_mode  # type: ignore[attr-defined]
    assert mode("opus-alone") == "alone"
    assert mode("opus-sanka-cli") == "sanka-cli"
    assert mode("opus-with-sanka") == "with-sanka"
    assert mode("opus-with-sanka-readiness-aware") == "readiness-aware"
    assert mode("opus-experimental") is None
    # sampled cells carry a -s<k> suffix (docs/measurement-design.md); the arm is unchanged
    assert mode("drf-fastapi-001-claude-opus48-alone-s2") == "alone"
    assert mode("drf-fastapi-001-claude-opus48-with-sanka-s10") == "with-sanka"
    assert mode("drf-fastapi-001-claude-opus48-with-sanka-readiness-aware-s3") == "readiness-aware"
    assert mode("drf-fastapi-001-claude-opus48-s1") is None


def test_readiness_context_abstains_and_sends_only_readiness_and_verifier(
    harness: object,
) -> None:
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
    # the inventory is frozen for the record ...
    assert context["skipped_routes"][0]["view"] == "legacy_project.urls.permanent_style_redirect"
    prompt = harness._readiness_prompt(context, Path("/tools/sanka"))  # type: ignore[attr-defined]
    assert "3.4% (1/29" in prompt
    assert "did not generate a scaffold" in prompt
    assert "Do not run `sanka apply`" in prompt
    assert "/tools/sanka verify . --to fastapi --scenarios public-tests/scenarios.json" in prompt
    assert "--edge-probes" in prompt
    # ... but never sent as a checklist: no route codes, no unscanned patterns,
    # no critic list (instructions without capability only raise cost)
    assert "SANKA_DRF_ROUTE_PATTERN_UNSUPPORTED" not in prompt
    assert "permanent_style_redirect" not in prompt
    assert "GET /api/dynamic/entries/{code}/" not in prompt
    assert "Allow, Location, and WWW-Authenticate" not in prompt
    assert "checklist" not in prompt.lower()


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
    prompt = harness._readiness_prompt(context, Path("/tools/sanka"))  # type: ignore[attr-defined]
    assert "generated `bench-candidate/overlay/`" in prompt
    assert "/tools/sanka verify . --to fastapi" in prompt
    assert "checklist" not in prompt.lower()


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
                "routes": [
                    {
                        "automatic": False,
                        "method": "GET",
                        "path": "/api/x/",
                        "operation": "list",
                        "strategy": "needs-manual-adaptation",
                        "adaptation_reasons": [],
                        "parity_notes": [
                            {
                                "family": "routing",
                                "code": "SANKA_DRF_PARITY_ALLOWED_METHODS",
                                "message": "Allowed methods on this path: GET, HEAD, OPTIONS.",
                                "source": None,
                            }
                        ],
                    }
                ],
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

    def fake_run(
        command: list[str], *, workspace: Path, env: dict[str, str], **_kwargs: object
    ) -> SimpleNamespace:
        assert workspace == tmp_path
        assert env == {"BENCH": "1"}
        if command[1] == "apply":
            # sanka refuses to apply once the workspace fingerprint changed, so the
            # parity-notes file must not exist yet when apply runs
            assert not (tmp_path / "sanka-parity-notes.md").exists()
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
    # the tool is installed for the agent first (marketplace snapshot + project lock),
    # then scan, then a headless plan with its inputs spelled out
    assert [command[1] for command in commands] == [
        "extension",
        "extension",
        "scan",
        "plan",
        *(("apply",) if expects_apply else ()),
    ]
    assert commands[2][-1] == "--json" and commands[3][-1] == "--json"
    assert commands[0][2:4] == ["marketplace", "add"]
    assert commands[1][2:4] == ["add", "sanka/drf-to-fastapi"]
    assert commands[3][2:5] == [".", "--to", "fastapi"]
    assert commands[3][5:-3] == [
        "--strategy",
        "native",
        "--generation",
        "minimal",
        "--package-manager",
        "uv",
        "--output",
        ".sanka/output/fastapi",
    ]
    assert all(command[-3:-1] == ["--extension-env", "PYTHONPATH"] for command in commands[2:])
    if expects_apply:
        assert "--plan-hash" in commands[-1]
        assert "sha256:preflight" in commands[-1]
    # the notes file is written for the agent once the scaffold decision is settled
    assert (tmp_path / "sanka-parity-notes.md").exists()


def test_as_text_normalizes_timeout_output(harness: object) -> None:
    as_text = harness._as_text  # type: ignore[attr-defined]
    assert as_text(None) == ""
    assert as_text(b"partial \xff output") == "partial � output"
    assert as_text("already text") == "already text"


@pytest.mark.parametrize(
    ("event_type", "expected"),
    [("system", False), ("assistant", True), ("result", True), ("tool_use", True)],
)
def test_timeout_activity_requires_a_model_event(
    harness: object, event_type: str, expected: bool
) -> None:
    stdout = json.dumps({"type": event_type, "subtype": "init"}) + "\n"
    assert harness._has_model_activity(stdout) is expected  # type: ignore[attr-defined]


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


def test_install_sanka_skill_is_project_local_and_digest_verified(
    harness: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = b"---\nname: sanka-cli\n---\n"
    target = tmp_path / ".claude" / "skills" / "sanka-cli"
    commands: list[list[str]] = []

    def fake_run(
        command: list[str], *, workspace: Path, env: dict[str, str], **_kwargs: object
    ) -> SimpleNamespace:
        assert workspace == tmp_path
        assert env == {"PATH": "/bin"}
        commands.append(command)
        target.mkdir(parents=True, exist_ok=True)
        (target / "SKILL.md").write_bytes(content)
        return SimpleNamespace(
            stdout=json.dumps(
                {
                    "skill": "sanka-cli",
                    "scope": "project",
                    "content_sha256": hashlib.sha256(content).hexdigest(),
                    "installations": [
                        {"harness": "claude", "path": str(target), "status": "installed"}
                    ],
                }
            )
        )

    monkeypatch.setattr(harness, "_run_sanka_command", fake_run)

    record = harness.install_sanka_skill(  # type: ignore[attr-defined]
        Path("/tools/sanka"), tmp_path, {"PATH": "/bin"}
    )

    assert commands == [
        [
            "/tools/sanka",
            "--output",
            "json",
            "skill",
            "install",
            "claude",
            "--scope",
            "project",
            "--project-dir",
            str(tmp_path),
        ]
    ]
    assert record == {
        "scope": "project",
        "path": str(target),
        "status": "installed",
        "content_sha256": hashlib.sha256(content).hexdigest(),
    }
    with pytest.raises(RuntimeError, match="pinned manifest digest"):
        harness.install_sanka_skill(  # type: ignore[attr-defined]
            Path("/tools/sanka"), tmp_path, {"PATH": "/bin"}, "sha256:" + "0" * 64
        )


def test_install_sanka_skill_rejects_a_false_digest(
    harness: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / ".claude" / "skills" / "sanka-cli"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("installed content\n", encoding="utf-8")
    monkeypatch.setattr(
        harness,
        "_run_sanka_command",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout=json.dumps(
                {
                    "skill": "sanka-cli",
                    "scope": "project",
                    "content_sha256": "0" * 64,
                    "installations": [
                        {"harness": "claude", "path": str(target), "status": "installed"}
                    ],
                }
            )
        ),
    )

    with pytest.raises(RuntimeError, match="digest mismatch"):
        harness.install_sanka_skill(Path("/tools/sanka"), tmp_path, {})  # type: ignore[attr-defined]


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
    # Codex 0.150 enables a server-side web-search tool by default; Fireworks'
    # Responses API rejects it alongside function tools, so it is off everywhere.
    assert 'web_search="disabled"' in command
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
    pre_sleep_events: list[dict] | None = None,
    sleep_seconds: int = 0,
) -> Path:
    """Emulate the Claude CLI: print stream events then the result, and exit 1
    whenever the result reports ``is_error`` (the real CLI does exactly that on
    ``error_max_turns``). ``result=None`` prints nothing at all."""
    script = tmp_path / "fake-agent"
    if exit_code is None:
        exit_code = 1 if (result or {}).get("is_error") else 0
    events = preamble if preamble is not None else [{"type": "system", "subtype": "init"}]
    events = [
        {"skills": [], "tools": ["Bash", "Read", "Write", "Edit", "Skill"], **event}
        if event.get("subtype") == "init"
        else event
        for event in events
    ]
    lines = [json.dumps(event) for event in events]
    if result is not None:
        lines.append(json.dumps(result))
    prints = "".join(f"printf '%s\\n' '{line}'\n" for line in lines)
    early_prints = "".join(
        f"printf '%s\\n' '{json.dumps(event)}'\n" for event in (pre_sleep_events or [])
    )
    touch_line = f"touch '{touch}'" if touch else ":"
    script.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "--version" ]; then echo fake-agent-1.0; exit 0; fi\n'
        'printf \'%s\\n\' "$@" > "$CLAUDE_CONFIG_DIR/fake-agent-argv.txt"\n'
        'printf \'%s\' "$0" > "$CLAUDE_CONFIG_DIR/fake-agent-executable.txt"\n'
        f"printf '%s\\n' \"${{CLAUDE_CONFIG_DIR:-}}\" > "
        f'"$CLAUDE_CONFIG_DIR/fake-agent-claude-config.txt"\n'
        f'printf \'%s\' "${{UNRELATED_SECRET:-}}" > "$CLAUDE_CONFIG_DIR/fake-agent-secret.txt"\n'
        f'printf \'%s\' "${{OPENAI_API_KEY:-}}" > "$CLAUDE_CONFIG_DIR/fake-agent-openai-key.txt"\n'
        f"printf '%s' \"${{ANTHROPIC_AUTH_TOKEN:-}}\" > "
        f'"$CLAUDE_CONFIG_DIR/fake-agent-anthropic-token.txt"\n'
        f'printf \'%s\' "$PATH" > "$CLAUDE_CONFIG_DIR/fake-agent-path.txt"\n'
        f'command -v sanka > "$CLAUDE_CONFIG_DIR/fake-agent-sanka.txt" 2>/dev/null || true\n'
        f"{touch_line}\n"
        f"{early_prints}"
        f"sleep {sleep_seconds}\n"
        f"{prints}"
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def _run_adapter(
    task: Path,
    agent: Path,
    out: Path,
    sandbox: Path | None = None,
    extra_args: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [
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
    ]
    if sandbox is not None:
        command.extend(["--sandbox", str(sandbox)])
    command.extend(extra_args or [])
    sandbox = sandbox or out.parent / "sandbox"
    if "--sandbox" not in command:
        command.extend(["--sandbox", str(sandbox)])
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    for path in (sandbox / "claude-config").glob("fake-agent-*.txt"):
        (out.parent / path.name).write_bytes(path.read_bytes())
    return result


def test_persistent_sandbox_keeps_workspace_config_and_raw_stream(tmp_path: Path) -> None:
    task = Path(__file__).resolve().parents[1] / "tasks" / "drf-fastapi" / "drf-fastapi-001"
    agent = _fake_agent(
        tmp_path,
        result={
            "num_turns": 1,
            "duration_ms": 1000,
            "total_cost_usd": 0.1,
            "is_error": False,
            "subtype": "success",
            "result": "done",
        },
        touch="target_app.py",
    )
    sandbox = tmp_path / "sandbox"

    outcome = _run_adapter(task, agent, tmp_path / "candidate", sandbox)

    assert outcome.returncode == 0, outcome.stderr
    assert (sandbox / "workspace" / "target_app.py").is_file()
    assert (sandbox / "claude-config").is_dir()
    assert (sandbox / "raw" / "agent-log.jsonl").is_file()
    assert (tmp_path / "fake-agent-claude-config.txt").read_text().strip() == str(
        sandbox / "claude-config"
    )
    argv = (tmp_path / "fake-agent-argv.txt").read_text().splitlines()
    assert argv[argv.index("--setting-sources") + 1] == "project"
    assert "--dangerously-skip-permissions" not in argv
    assert "--disable-slash-commands" in argv


def test_agent_symlink_invokes_the_mounted_executable(tmp_path: Path) -> None:
    task = SCRIPTS.parent / "tasks/drf-fastapi/drf-fastapi-001"
    agent = _fake_agent(
        tmp_path,
        result={"num_turns": 1, "is_error": False, "subtype": "success"},
        touch="target_app.py",
    )
    alias = tmp_path / "claude-alias"
    alias.symlink_to(agent)
    result = _run_adapter(task, alias, tmp_path / "candidate")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "fake-agent-executable.txt").read_text() == str(agent.resolve())


def test_contaminated_skill_inventory_is_preserved_but_not_scored(tmp_path: Path) -> None:
    task = SCRIPTS.parent / "tasks/drf-fastapi/drf-fastapi-001"
    agent = _fake_agent(
        tmp_path,
        result={"num_turns": 1, "is_error": False, "subtype": "success"},
        touch="target_app.py",
        preamble=[{"type": "system", "subtype": "init", "skills": ["sanka-bench-run"]}],
    )
    out = tmp_path / "candidate"
    result = _run_adapter(task, agent, out)
    assert result.returncode == 1
    assert "skill inventory" in result.stderr
    assert (out / "agent-log.jsonl").is_file()
    assert not (out / "candidate.yaml").exists()


def test_alone_agent_cannot_inherit_host_secrets_or_global_sanka(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = Path(__file__).resolve().parents[1] / "tasks" / "drf-fastapi" / "drf-fastapi-001"
    global_bin = tmp_path / "global-bin"
    global_bin.mkdir()
    (global_bin / "sanka").write_text("#!/bin/sh\n", encoding="utf-8")
    (global_bin / "sanka").chmod(0o755)
    monkeypatch.setenv("PATH", f"{global_bin}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("UNRELATED_SECRET", "must-not-reach-agent")
    agent = _fake_agent(
        tmp_path,
        result={"num_turns": 1, "is_error": False, "subtype": "success"},
        touch="target_app.py",
    )

    outcome = _run_adapter(task, agent, tmp_path / "candidate")

    assert outcome.returncode == 0, outcome.stderr
    assert (tmp_path / "fake-agent-secret.txt").read_text() == ""
    assert (tmp_path / "fake-agent-path.txt").read_text() == os.defpath
    assert (tmp_path / "fake-agent-sanka.txt").read_text() == ""


def test_gateway_agent_receives_only_anthropic_compatible_route_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = Path(__file__).resolve().parents[1] / "tasks" / "drf-fastapi" / "drf-fastapi-001"
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-claude")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "gateway-token")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gateway.test")
    agent = _fake_agent(
        tmp_path,
        result={"num_turns": 1, "is_error": False, "subtype": "success"},
        touch="target_app.py",
    )

    outcome = _run_adapter(
        task,
        agent,
        tmp_path / "candidate",
        extra_args=["--route-kind", "gateway", "--billing-mode", "api_key"],
    )

    assert outcome.returncode == 0, outcome.stderr
    assert (tmp_path / "fake-agent-openai-key.txt").read_text() == ""
    assert (tmp_path / "fake-agent-anthropic-token.txt").read_text() == "gateway-token"


def test_persistent_sandbox_refuses_a_nonempty_workspace(tmp_path: Path) -> None:
    task = Path(__file__).resolve().parents[1] / "tasks" / "drf-fastapi" / "drf-fastapi-001"
    agent = _fake_agent(tmp_path, result=None, touch=None)
    sandbox = tmp_path / "sandbox"
    workspace = sandbox / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "prior-attempt.txt").write_text("keep me\n", encoding="utf-8")

    outcome = _run_adapter(task, agent, tmp_path / "candidate", sandbox)

    assert outcome.returncode == 2
    assert "sandbox workspace is not empty" in outcome.stderr
    assert (workspace / "prior-attempt.txt").read_text() == "keep me\n"


@pytest.mark.parametrize(
    "subtype,disclosure_text",
    [
        ("error_max_turns", "turn budget (60)"),
        ("error_max_budget_usd", "agent estimated-cost budget (5.0 USD)"),
    ],
)
def test_budget_exhaustion_freezes_the_workspace(
    tmp_path: Path, subtype: str, disclosure_text: str
) -> None:
    task = Path(__file__).resolve().parents[1] / "tasks" / "drf-fastapi" / "drf-fastapi-001"
    agent = _fake_agent(
        tmp_path,
        result={
            "num_turns": 60,
            "duration_ms": 1000,
            "total_cost_usd": 0.1,
            "is_error": True,
            "subtype": subtype,
            "result": "max turns reached",
        },
        touch="target_app.py",
    )
    out = tmp_path / "candidate"
    outcome = _run_adapter(task, agent, out, extra_args=["--max-agent-cost-usd", "5"])
    # The fake exits 1 like the real CLI does on error_max_turns; the parsed
    # result must still win over the exit code and the workspace must freeze.
    assert outcome.returncode == 0, outcome.stderr
    assert (out / "overlay" / "target_app.py").is_file()
    disclosure = (out / "GENERATED.md").read_text(encoding="utf-8")
    assert disclosure_text + " exhausted" in disclosure
    assert "frozen as-is" in disclosure
    argv = (tmp_path / "fake-agent-argv.txt").read_text(encoding="utf-8").splitlines()
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert "--verbose" in argv
    assert argv[argv.index("--max-budget-usd") + 1] == "5.0"


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
    telemetry = json.loads((out / "telemetry.json").read_text(encoding="utf-8"))
    assert telemetry["schema"] == "sanka-bench/agent-cell-telemetry/v1"
    assert telemetry["digests"]["transcript_sha256"].startswith("sha256:")
    assert telemetry["digests"]["overlay_sha256"].startswith("sha256:")
    assert telemetry["timing"]["agent_wall_seconds"] >= 0
    candidate = load_and_validate(out / "candidate.yaml", "candidate")
    assert candidate["stats"]["actual_model_id"] == "claude-sonnet-5"


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


def test_completed_empty_workspace_is_frozen_as_a_quality_failure(tmp_path: Path) -> None:
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
    assert outcome.returncode == 0, outcome.stderr
    assert (out / "overlay").is_dir()
    assert list((out / "overlay").iterdir()) == []
    assert (out / "candidate.yaml").is_file()


def test_silent_timeout_without_workspace_activity_is_an_infrastructure_failure(
    tmp_path: Path,
) -> None:
    task = Path(__file__).resolve().parents[1] / "tasks" / "drf-fastapi" / "drf-fastapi-001"
    agent = _fake_agent(
        tmp_path,
        result=None,
        touch=None,
        pre_sleep_events=[{"type": "system", "subtype": "init"}],
        sleep_seconds=2,
    )
    out = tmp_path / "candidate"

    outcome = _run_adapter(
        task,
        agent,
        out,
        extra_args=["--wall-clock-seconds", "1"],
    )

    assert outcome.returncode == 1
    assert "agent reported an error: wall-clock timeout" in outcome.stderr
    assert not (out / "overlay").exists()


def test_timeout_with_workspace_activity_is_frozen_for_scoring(tmp_path: Path) -> None:
    task = Path(__file__).resolve().parents[1] / "tasks" / "drf-fastapi" / "drf-fastapi-001"
    agent = _fake_agent(
        tmp_path,
        result=None,
        touch="target_app.py",
        sleep_seconds=2,
    )
    out = tmp_path / "candidate"

    outcome = _run_adapter(
        task,
        agent,
        out,
        extra_args=["--wall-clock-seconds", "1"],
    )

    assert outcome.returncode == 0, outcome.stderr
    assert (out / "overlay" / "target_app.py").is_file()
    assert "wall-clock timeout (1s) exhausted" in (out / "GENERATED.md").read_text()


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


def _plan_with_notes() -> dict[str, object]:
    note = {
        "family": "auth",
        "code": "SANKA_DRF_PARITY_UNAUTHENTICATED",
        "message": "a request without valid credentials answers 401 with WWW-Authenticate: Token",
        "source": None,
    }
    override = {
        "family": "overrides",
        "code": "SANKA_DRF_PARITY_VIEW_OVERRIDE",
        "message": "DocumentViewSet.get_permissions is overridden in project code.",
        "source": "documents/views.py:18",
    }
    return {
        "readiness": 0.0,
        "native_routes": 0,
        "native_eligible_routes": 2,
        "needs_adaptation_routes": 2,
        "plan_hash": "sha256:notes",
        "routes": [
            {
                "automatic": False,
                "method": "GET",
                "path": "/api/documents/{pk}/",
                "operation": "retrieve",
                "strategy": "needs-manual-adaptation",
                "adaptation_reasons": [],
                "parity_notes": [note, override],
            },
            {
                "automatic": False,
                "method": "GET",
                "path": "/api/documents.{format}/",
                "operation": "list",
                "strategy": "dropped-format-suffix-alias",
                "adaptation_reasons": [],
                "parity_notes": [note],
            },
            {
                "automatic": True,
                "method": "GET",
                "path": "/api/",
                "operation": "get",
                "strategy": "native-fastapi-api-root",
                "adaptation_reasons": [],
                "parity_notes": [note],
            },
        ],
    }


def test_parity_notes_are_written_for_the_agent_and_named_once_in_the_prompt(
    harness: object, tmp_path: Path
) -> None:
    plan = _plan_with_notes()
    context = harness._readiness_context(plan, 0.5)  # type: ignore[attr-defined]
    path = harness._write_parity_notes(tmp_path, plan, context)  # type: ignore[attr-defined]
    assert path == tmp_path / "sanka-parity-notes.md"
    text = path.read_text(encoding="utf-8")
    # below the threshold every non-alias route is hand-written, so every one is listed
    assert "## GET /api/documents/{pk}/" in text
    assert "## GET /api/" in text
    assert "## GET /api/documents.{format}/" not in text
    assert "- [auth] a request without valid credentials answers 401" in text
    assert "(documents/views.py:18)" in text
    assert context["parity_note_count"] == 3
    assert context["parity_note_routes"] == 2
    prompt = harness._readiness_prompt(context, Path("/tools/sanka"))  # type: ignore[attr-defined]
    assert prompt.count("sanka-parity-notes.md") == 1
    assert "3 notes over 2 routes" in prompt
    assert "checklist" not in prompt.lower()
    # the file is workspace guidance, never part of the frozen candidate overlay
    assert "sanka-parity-notes.md" in harness.EXCLUDED_NAMES  # type: ignore[attr-defined]


def test_parity_notes_skip_generated_routes_and_older_plans(
    harness: object, tmp_path: Path
) -> None:
    plan = _plan_with_notes()
    plan.update({"readiness": 0.75, "native_routes": 3, "native_eligible_routes": 4})
    context = harness._readiness_context(plan, 0.5)  # type: ignore[attr-defined]
    assert context["decision"] == "emit-scaffold"
    path = harness._write_parity_notes(tmp_path, plan, context)  # type: ignore[attr-defined]
    assert path is not None
    text = path.read_text(encoding="utf-8")
    assert "## GET /api/documents/{pk}/" in text
    assert "## GET /api/\n" not in text  # generated by the scaffold, not hand-written
    legacy = dict(_plan_with_notes())
    legacy["routes"] = [
        {k: v for k, v in route.items() if k != "parity_notes"}  # type: ignore[union-attr]
        for route in legacy["routes"]  # type: ignore[union-attr]
    ]
    older = harness._readiness_context(legacy, 0.5)  # type: ignore[attr-defined]
    workspace = tmp_path / "older"
    workspace.mkdir()
    assert harness._write_parity_notes(workspace, legacy, older) is None  # type: ignore[attr-defined]
    assert not (workspace / "sanka-parity-notes.md").exists()
    assert "sanka-parity-notes.md" not in harness._readiness_prompt(  # type: ignore[attr-defined]
        older, Path("/tools/sanka")
    )


def test_sanka_artifact_prefers_the_cli_listing_then_the_extension_directory(
    harness: object, tmp_path: Path
) -> None:
    locate = harness._sanka_artifact  # type: ignore[attr-defined]
    listed = tmp_path / "elsewhere" / "plan-fastapi.json"
    listed.parent.mkdir()
    listed.write_text("{}", encoding="utf-8")
    payload = json.dumps({"artifacts": [str(listed)]})
    assert locate(payload, "plan-fastapi.json", tmp_path) == listed
    nested = tmp_path / ".sanka" / "extensions" / "sanka" / "drf-to-fastapi" / "scan.json"
    nested.parent.mkdir(parents=True)
    nested.write_text("{}", encoding="utf-8")
    assert locate("", "scan.json", tmp_path) == nested
    legacy = tmp_path / ".sanka" / "plan-fastapi.json"
    legacy.write_text("{}", encoding="utf-8")
    assert locate("not json", "plan-fastapi.json", tmp_path) == legacy
    with pytest.raises(RuntimeError):
        locate("", "missing.json", tmp_path)


def test_scaffold_preserves_source_and_rejects_symlinks(harness, tmp_path):
    overlay = tmp_path / "bench-candidate" / "overlay"
    overlay.mkdir(parents=True)
    (tmp_path / "settings.py").write_text("original")
    (overlay / "settings.py").write_text("generated")
    (overlay / "target_app.py").write_text("native")
    files = harness._promote_scaffold(tmp_path)
    assert set(files) == {"target_app.py"}
    assert (tmp_path / "settings.py").read_text() == "original"
    assert (tmp_path / "target_app.py").read_text() == "native"
    (overlay / "escape").symlink_to(tmp_path.parent)
    with pytest.raises(RuntimeError, match="Unsafe"):
        harness._promote_scaffold(tmp_path)
    with pytest.raises(RuntimeError, match="escapes workspace"):
        harness._sanka_artifact('{"artifacts":["../scan.json"]}', "scan.json", tmp_path)


@pytest.mark.parametrize("mode", ["sanka-cli", "with-sanka"])
@pytest.mark.parametrize("silent_timeout", [False, True])
def test_artifacts_first_reuses_scaffold_without_hiding_silent_timeout(
    harness, tmp_path, monkeypatch, mode, silent_timeout
):
    agent = _fake_agent(tmp_path, result={"num_turns": 1}, touch=False)
    task = SCRIPTS.parent / "tasks" / "drf-fastapi" / "drf-fastapi-001"
    out = tmp_path / "candidate"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_agent_candidate",
            "--task",
            str(task),
            "--candidate-id",
            f"fake-{mode}",
            "--out",
            str(out),
            "--sandbox",
            str(tmp_path / "sandbox"),
            "--agent-bin",
            str(agent),
            "--sanka-bin",
            str(agent),
            "--sanka-workflow",
            "artifacts-first-v1",
        ],
    )

    def prepare(workspace, *_args):
        overlay = workspace / "bench-candidate" / "overlay"
        overlay.mkdir(parents=True)
        (overlay / "target_app.py").write_text("generated")
        return {
            "decision": "emit-scaffold",
            "readiness": 1,
            "threshold": 0.5,
            "native_routes": 1,
            "native_eligible_routes": 1,
            "plan_hash": "test",
        }

    monkeypatch.setattr(harness, "_prepare_readiness_context", prepare)
    monkeypatch.setattr(harness, "install_sanka_skill", lambda *_args: {"sha256": "test"})
    monkeypatch.setattr(harness, "_sanka_tool_versions", lambda *_args, **_kw: "test")

    def run(command, *, workspace, **_kwargs):
        assert (workspace / "target_app.py").read_text() == "generated"
        assert "already installed" in command[2]
        if silent_timeout:
            raise subprocess.TimeoutExpired(command, 1, output="")
        stdout = (
            json.dumps(
                {
                    "type": "system",
                    "subtype": "init",
                    "skills": ["sanka-cli"] if mode == "with-sanka" else [],
                }
            )
            + "\n"
        )
        stdout += json.dumps({"type": "result", "num_turns": 1, "subtype": "success"})
        return subprocess.CompletedProcess(command, 0, stdout, "")

    monkeypatch.setattr(harness.agent_isolation, "run", run)
    assert harness.main() == (1 if silent_timeout else 0)
    telemetry = json.loads((out / "telemetry.json").read_text())
    assert telemetry["treatment"]["agent_changed_files"] == 0
    assert telemetry["treatment"]["generated_files_retained_unchanged"] == 1
    assert (out / "overlay" / "target_app.py").exists() is not silent_timeout


def test_observed_work_deduplicates_streamed_events(harness):
    event = json.dumps(
        {
            "type": "assistant",
            "message": {"id": "response1", "content": [{"type": "tool_use", "id": "tool1"}]},
        }
    )
    assert harness._observed_work(event + "\n" + event) == {
        "observed_model_responses": 1,
        "tool_calls": 1,
        "provider_api_requests": None,
        "provider_retries": None,
    }


def test_flask_prompt_and_readiness_do_not_advertise_fastapi_replay(harness, repository_root):
    prompt = harness.task_prompt(repository_root / "tasks/drf-flask/drf-flask-004", 60, 3600)
    assert "Flask" in prompt and "Flask URL rule" in prompt
    assert "FastAPI" not in prompt and "APIRoute" not in prompt
    context = harness._readiness_context(
        {"native_routes": 0, "native_eligible_routes": 4, "readiness": 0, "plan_hash": "reviewed"},
        0.5,
    )
    context["target_framework"] = "flask"
    rendered = harness._readiness_prompt(context, Path("/tools/sanka"))
    assert "does not yet provide differential replay" in rendered
    assert "--to fastapi" not in rendered
