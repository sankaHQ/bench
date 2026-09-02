"""Produce a frozen coding-agent candidate for one benchmark task.

Runs a command-line coding agent headlessly against a pristine copy of the
task's source with a fixed migration prompt, collects every file the agent
added as the candidate overlay, and writes the candidate with full
disclosure: model, tool version, prompt verbatim, turn budget, turns used,
duration, and reported cost. The agent runs unattended — no human
intervention — and the frozen overlay is then graded by the ordinary
tool-neutral evaluator like any other candidate.

Three configurations preserve the official two-arm benchmark and add one
separate diagnostic arm:

- ``--candidate-id claude-code-alone`` — the agent and the task, nothing else;
- ``--candidate-id claude-code-with-sanka`` (with ``--sanka-bin``) — the same
  agent, same budget, same contract, plus the Sanka CLI and readiness-aware
  guidance for adopting or declining its generated candidate.
- ``--candidate-id claude-code-with-sanka-readiness-aware`` — the harness runs
  scan/plan first, generates a scaffold only at or above the configured native
  readiness threshold, and otherwise gives the agent a structured unsupported-
  route checklist. This arm is diagnostic and never replaces the official
  pass@1 configurations.

Two agent families share the same contract, prompt, and freezing logic:

- ``--agent claude-code`` (default) drives the Claude CLI headlessly and uses
  its self-reported turns, duration, and cost;
- ``--agent codex`` drives OpenAI's Codex CLI (``codex exec``) against the
  OpenAI API or any OpenAI-compatible provider (``--provider deepinfra``,
  ``fireworks``, ``together``). Codex does not self-report dollar cost, so the
  run records measured wall-clock and token usage, and computes cost from the
  per-model prices passed via ``--price-in``/``--price-out`` (USD per million
  tokens) — the disclosure names that basis explicitly.

Candidate ids stay free-form (``<agent>-<model-slug>-alone`` /
``...-with-sanka`` / ``...-with-sanka-readiness-aware``); the suffix selects
the run configuration.

Budget enforcement differs by agent and is disclosed, never papered over:
``--max-turns`` reaches the Claude CLI, while Codex CLI 0.150 exposes no turn
bound, so codex cells are bounded only by the 3600-second wall-clock timeout —
GENERATED.md states which limit actually applied.

Exit codes tell the run driver what happened, so exhaustion is still
evaluated while infrastructure failures stay out of the quality columns:

- ``0`` — a candidate was frozen. That includes runs that exhausted the turn
  budget or the wall-clock timeout with work in the workspace: the workspace
  is frozen as-is and the terminal reason is disclosed in GENERATED.md, so the
  evaluator grades what the agent actually produced instead of scoring an
  unevaluated zero.
- ``1`` — the agent reported an error (other than budget exhaustion) or the
  run produced no parseable result; nothing is frozen. Classify before any
  authorized rerun. The process exit code alone never decides this: Claude
  Code exits 1 on ``error_max_turns`` while still printing a complete result
  event, so the parsed result is authoritative and only an unparseable run
  with a non-zero exit is an agent-run failure.

Claude cells are captured with ``--output-format stream-json --verbose``:
``agent-log.jsonl`` holds the whole per-turn transcript (assistant events,
tool calls, tool results, final result) and ``agent-result.json`` holds the
final result event, so turn accounting never depends on the CLI's own session
store.
- ``2`` — usage error (bad arguments / not a benchmark task).
- ``3`` — the agent finished without adding a single file; nothing is frozen.
  An empty workspace together with no error event and no recorded turns is the
  signature of a silent provider failure — record it in the infrastructure
  ledger instead of charging it as a quality result.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PROMPT_CORE = """Migrate this Django REST Framework application to FastAPI, natively.

Deliverable contract (an automated evaluator enforces all of it):
1. Add new files only - never modify or delete existing source files.
2. Expose the FastAPI application as `app` in a new file `target_app.py` at the
   repository root.
3. The serving process must not import `rest_framework` or Django's
   request-serving machinery (`django.core.asgi`, `django.core.wsgi`,
   `django.core.handlers`, `django.test`). Django stays for the ORM only:
   create separate serving settings that remove every rest_framework app from
   INSTALLED_APPS, and point Django at them from target_app.py.
4. Behavior must match the original application exactly for every request in
   `public-tests/scenarios.json`: status codes, JSON bodies including exact
   error strings, and the resulting database rows. The evaluator seeds the
   database itself, replays each scenario against both applications from
   identical snapshots, repeats runs, and rejects nondeterminism. The public
   scenarios are a representative sample, not the grading set: the evaluator
   replays a hidden superset that adds edge cases and captures declared
   response headers (redirects included), so match the source application's
   exact semantics — headers, error wording, edge-case validation — rather
   than tuning for the public list alone.
5. The database path comes from the BENCH_DB_PATH environment variable through
   the existing settings module; reuse that mechanism unchanged.
6. Every evaluated request must be served by a FastAPI `APIRoute` whose endpoint
   code lives inside the candidate workspace. Do not use a raw Starlette `Route`,
   an automatic framework redirect, a mount, a compatibility bridge, or a
   source-framework dispatcher to serve evaluated requests.

A Python interpreter with django, djangorestframework, and fastapi installed
is available at: {python}
Use it to run the original app and your app side by side (django test client
vs fastapi TestClient) and verify every scenario before you finish. Do not
consider the task done until every scenario matches exactly.
"""

PROMPT_SANKA = """
The Sanka migration CLI is installed at: {sanka}
It can scan the source, report how much of it it can migrate natively, and
generate FastAPI code for the routes it supports:

    {sanka} scan .
    {sanka} plan --to fastapi
    {sanka} apply --root . --bench-candidate ./bench-candidate

Read the plan's readiness report before adopting anything: it states, per
route, whether native generation is supported and why not when it is not
(`plan --to fastapi --json` prints the full detail). At high readiness the
generated overlay under bench-candidate/overlay/ is a strong starting point —
copy the generated files and continue from them. At low readiness apply may
refuse outright or emit only a few routes; treat whatever it produces as
reference material, not as the thing to submit. Either way the original
application remains the specification: derive every route's exact semantics
from the source and verify by differential testing against it, never against
the generated code.
"""

PROMPT_SANKA_READINESS = """
The Sanka migration CLI preflight has already scanned and planned this source.
Native readiness is {readiness_percent:.1f}% ({native_routes}/{eligible_routes}
non-alias routes) against a {threshold_percent:.1f}% scaffold threshold.
Plan hash: {plan_hash}

{decision}

Unsupported-route checklist from the frozen Sanka plan:
{checklist}

URL patterns the Sanka scan saw but did not classify as DRF routes:
{skipped_checklist}

Post-generation critic checklist (the evaluator checks these independently):
- Every source route is covered, including explicit slash/no-slash variants.
- Status, JSON/body bytes, Allow, Location, and WWW-Authenticate match exactly.
- Successful and rejected mutations leave every database table in the same
  state as the source application.

Treat this checklist as migration guidance, not as permission to weaken the
deliverable contract. Verify the public scenarios and the exact FastAPI serving
behavior before you finish.
"""

EXCLUDED_PARTS = {
    ".claude",
    ".git",
    ".sanka",
    ".venv",
    "__pycache__",
    "bench-candidate",
    "node_modules",
    "public-tests",
}
EXCLUDED_SUFFIXES = {".log", ".pyc", ".sqlite3"}
EXCLUDED_NAMES = {".DS_Store", "AGENT_TASK.md", "CLAUDE.md"}


def _candidate_mode(candidate_id: str) -> str | None:
    if candidate_id.endswith("-with-sanka-readiness-aware"):
        return "readiness-aware"
    if candidate_id.endswith("-with-sanka"):
        return "with-sanka"
    if candidate_id.endswith("-alone"):
        return "alone"
    return None


def _readiness_context(
    plan: dict[str, object],
    threshold: float,
    scan: dict[str, object] | None = None,
) -> dict[str, object]:
    readiness = float(plan.get("readiness") or 0.0)
    native_routes = int(plan.get("native_routes") or 0)
    eligible_routes = int(plan.get("native_eligible_routes") or 0)
    routes: list[dict[str, object]] = []
    for item in plan.get("routes") or []:
        if not isinstance(item, dict) or item.get("automatic") is True:
            continue
        if item.get("strategy") == "dropped-format-suffix-alias":
            continue
        reasons = [
            reason for reason in item.get("adaptation_reasons") or [] if isinstance(reason, dict)
        ]
        routes.append(
            {
                "method": str(item.get("method") or ""),
                "path": str(item.get("path") or ""),
                "operation": str(item.get("operation") or ""),
                "reasons": reasons,
            }
        )
    return {
        "schema": "sanka-bench/readiness-preflight/v1",
        "threshold": threshold,
        "readiness": readiness,
        "native_routes": native_routes,
        "native_eligible_routes": eligible_routes,
        "needs_adaptation_routes": int(plan.get("needs_adaptation_routes") or len(routes)),
        "plan_hash": str(plan.get("plan_hash") or ""),
        "decision": "emit-scaffold"
        if native_routes > 0 and readiness >= threshold
        else "gap-report-only",
        "unsupported_routes": routes,
        "skipped_routes": [
            {
                "pattern": str(item.get("pattern") or ""),
                "view": str(item.get("view") or ""),
                "reason": str(item.get("reason") or "not classified as a DRF route"),
            }
            for item in (scan or {}).get("skipped_routes", [])
            if isinstance(item, dict)
        ],
    }


def _readiness_prompt(context: dict[str, object]) -> str:
    routes = context["unsupported_routes"]
    assert isinstance(routes, list)
    lines: list[str] = []
    for route in routes:
        assert isinstance(route, dict)
        reasons = route.get("reasons") or []
        rendered = "; ".join(
            f"{reason.get('code')} ({reason.get('feature')}): {reason.get('message')}"
            for reason in reasons
            if isinstance(reason, dict)
        )
        route_label = f"{route.get('method')} {route.get('path')}"
        lines.append(f"- {route_label}: {rendered or 'manual adaptation required'}")
    checklist = "\n".join(lines) or "- none"
    skipped = context.get("skipped_routes") or []
    assert isinstance(skipped, list)
    skipped_checklist = (
        "\n".join(
            f"- {item.get('pattern')} -> {item.get('view')} ({item.get('reason')})"
            for item in skipped
            if isinstance(item, dict)
        )
        or "- none"
    )
    if context["decision"] == "emit-scaffold":
        decision = (
            "The harness generated `bench-candidate/overlay/`. Copy the complete "
            "overlay to the repository root, including non-Python artifacts, then "
            "adapt every checklist route."
        )
    else:
        decision = (
            "The harness intentionally did not generate a scaffold because readiness "
            "is below the threshold. Do not run `sanka apply`; implement the native "
            "FastAPI target from the source while using the checklist as guidance."
        )
    return PROMPT_SANKA_READINESS.format(
        readiness_percent=float(context["readiness"]) * 100,
        native_routes=context["native_routes"],
        eligible_routes=context["native_eligible_routes"],
        threshold_percent=float(context["threshold"]) * 100,
        plan_hash=context["plan_hash"],
        decision=decision,
        checklist=checklist,
        skipped_checklist=skipped_checklist,
    )


def _run_sanka_command(
    command: list[str], *, workspace: Path, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    outcome = subprocess.run(
        command,
        cwd=workspace,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if outcome.returncode != 0:
        detail = outcome.stderr.strip() or outcome.stdout.strip() or "no output"
        raise RuntimeError(f"Sanka preflight failed ({' '.join(command[:2])}): {detail[:2000]}")
    return outcome


def _sanka_runtime_env(env: dict[str, str]) -> dict[str, str]:
    """Expose fixture dependencies to a Sanka CLI in an isolated virtualenv."""
    updated = dict(env)
    fixture_paths = [
        entry
        for entry in sys.path
        if entry and Path(entry).name in {"site-packages", "dist-packages"}
    ]
    paths = list(dict.fromkeys(fixture_paths))
    if paths:
        updated["PYTHONPATH"] = os.pathsep.join(paths)
    else:
        updated.pop("PYTHONPATH", None)
    return updated


def _prepare_readiness_context(
    workspace: Path,
    sanka_bin: Path,
    env: dict[str, str],
    threshold: float,
) -> dict[str, object]:
    _run_sanka_command([str(sanka_bin), "scan", "."], workspace=workspace, env=env)
    _run_sanka_command(
        [str(sanka_bin), "plan", ".", "--to", "fastapi"],
        workspace=workspace,
        env=env,
    )
    plan_path = workspace / ".sanka" / "plan-fastapi.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if not isinstance(plan, dict):
        raise RuntimeError(f"Sanka plan is not an object: {plan_path}")
    scan_path = workspace / ".sanka" / "scan.json"
    scan = json.loads(scan_path.read_text(encoding="utf-8"))
    if not isinstance(scan, dict):
        raise RuntimeError(f"Sanka scan is not an object: {scan_path}")
    context = _readiness_context(plan, threshold, scan)
    if context["decision"] == "emit-scaffold":
        _run_sanka_command(
            [
                str(sanka_bin),
                "apply",
                "--root",
                ".",
                "--plan-hash",
                str(context["plan_hash"]),
                "--bench-candidate",
                "./bench-candidate",
            ],
            workspace=workspace,
            env=env,
        )
    return context


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument(
        "--candidate-id",
        required=True,
        help="<agent>-<model-slug>-alone or ...-with-sanka",
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--agent", default="claude-code", choices=("claude-code", "codex"))
    parser.add_argument("--agent-bin", default=None)
    parser.add_argument("--model", default="claude-sonnet-5")
    parser.add_argument(
        "--provider",
        default="openai",
        choices=("openai", "deepinfra", "fireworks", "together"),
        help="codex only: which OpenAI-compatible API serves the model",
    )
    parser.add_argument(
        "--provider-variant",
        default="standard",
        help=(
            "disclosed provider serving tier/deployment, for example "
            "serverless-standard or on-demand-fast; never changes implicitly"
        ),
    )
    parser.add_argument(
        "--price-in",
        type=float,
        default=None,
        help="codex only: USD per million input tokens, for computed cost",
    )
    parser.add_argument(
        "--price-out",
        type=float,
        default=None,
        help="codex only: USD per million output tokens, for computed cost",
    )
    parser.add_argument("--max-turns", type=int, default=60)
    parser.add_argument("--sanka-bin", type=Path, default=None)
    parser.add_argument(
        "--sanka-readiness-threshold",
        type=float,
        default=0.5,
        help="diagnostic readiness-aware arm: minimum native readiness for a scaffold",
    )
    parser.add_argument("--attempt", type=int, default=1)
    parser.add_argument(
        "--prior-failure",
        default=None,
        help="disclosed reason the previous attempt failed (infrastructure retries only)",
    )
    args = parser.parse_args()

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", args.provider_variant):
        print(
            "--provider-variant must be a slug containing only letters, digits, '.', '_' or '-'",
            file=sys.stderr,
        )
        return 2

    task_dir = args.task.resolve()
    source = task_dir / "source"
    scenarios = task_dir / "public-tests" / "scenarios.json"
    if not source.is_dir() or not scenarios.is_file():
        print(f"not a benchmark task: {task_dir}", file=sys.stderr)
        return 2
    mode = _candidate_mode(args.candidate_id)
    if mode is None:
        print(
            "candidate id must end in -alone, -with-sanka, or -with-sanka-readiness-aware",
            file=sys.stderr,
        )
        return 2
    if mode != "alone" and args.sanka_bin is None:
        print(f"{args.candidate_id} requires --sanka-bin", file=sys.stderr)
        return 2
    if not 0 <= args.sanka_readiness_threshold <= 1:
        print("--sanka-readiness-threshold must be between 0 and 1", file=sys.stderr)
        return 2
    if args.agent_bin is None:
        args.agent_bin = "claude" if args.agent == "claude-code" else "codex"

    agent_version = subprocess.run(
        [args.agent_bin, "--version"], capture_output=True, text=True, check=False
    ).stdout.strip()

    with tempfile.TemporaryDirectory(prefix="sanka-agent-") as temp:
        workspace = Path(temp) / "workspace"
        shutil.copytree(source, workspace)
        public_tests = workspace / "public-tests"
        public_tests.mkdir()
        shutil.copy2(scenarios, public_tests / "scenarios.json")

        env = dict(os.environ)
        for name in (
            "DJANGO_SETTINGS_MODULE",
            "BENCH_DB_PATH",
            "CLAUDECODE",
            "CLAUDE_CODE_ENTRYPOINT",
        ):
            env.pop(name, None)
        if mode != "alone":
            env = _sanka_runtime_env(env)
        readiness_context: dict[str, object] | None = None
        prompt = PROMPT_CORE.format(python=sys.executable)
        if mode == "with-sanka":
            assert args.sanka_bin is not None
            prompt += PROMPT_SANKA.format(sanka=args.sanka_bin.resolve())
        elif mode == "readiness-aware":
            assert args.sanka_bin is not None
            try:
                readiness_context = _prepare_readiness_context(
                    workspace,
                    args.sanka_bin.resolve(),
                    env,
                    args.sanka_readiness_threshold,
                )
            except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
                print(f"readiness-aware Sanka preflight failed: {exc}", file=sys.stderr)
                return 1
            prompt += _readiness_prompt(readiness_context)
        if args.agent == "codex":
            codex_home = Path(temp) / "codex-home"
            command = _codex_command(args, prompt, codex_home)
            env["CODEX_HOME"] = str(codex_home)
        else:
            command = [
                args.agent_bin,
                "-p",
                prompt,
                "--model",
                args.model,
                "--max-turns",
                str(args.max_turns),
                # stream-json keeps every assistant/tool event, so
                # agent-log.jsonl is the per-turn transcript instead of a copy
                # of the final result line; the result event stays last.
                "--output-format",
                "stream-json",
                "--verbose",
                "--dangerously-skip-permissions",
            ]
        terminal_reason: str | None = None
        timed_out = False
        started = time.monotonic()
        try:
            outcome = subprocess.run(
                command,
                cwd=workspace,
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=3600,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            # The transcript so far is evidence, not garbage: keep it, and
            # freeze whatever the agent managed to produce before the kill.
            timed_out = True
            outcome = subprocess.CompletedProcess(
                exc.cmd,
                returncode=124,
                stdout=_as_text(exc.stdout),
                stderr=_as_text(exc.stderr),
            )
            terminal_reason = (
                "wall-clock timeout (3600s) exhausted; the agent process was "
                "killed and the workspace was frozen as-is"
            )
        measured_ms = (time.monotonic() - started) * 1000
        if args.agent == "codex":
            stats = _codex_stats(outcome.stdout, args, measured_ms)
        else:
            stats = _agent_stats(outcome.stdout)
        out_dir = args.out.resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        raw = outcome.stdout.strip().splitlines()
        if raw:
            (out_dir / "agent-result.json").write_text(raw[-1] + "\n", encoding="utf-8")
        if outcome.stdout:
            (out_dir / "agent-log.jsonl").write_text(outcome.stdout, encoding="utf-8")
        if outcome.stderr:
            (out_dir / "agent-stderr.log").write_text(outcome.stderr, encoding="utf-8")
        if readiness_context is not None:
            (out_dir / "sanka-readiness.json").write_text(
                json.dumps(readiness_context, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        if not timed_out and outcome.returncode != 0 and not stats:
            # Only a run with no parseable terminal result is an agent-run
            # failure. A parseable result is authoritative over the process exit
            # code: Claude Code exits 1 on ``error_max_turns`` (verified against
            # CLI 2.1.241), and that budget outcome must reach the freeze branch
            # below instead of being misfiled as an infrastructure failure.
            detail = outcome.stderr.strip()[:2000] or "no output"
            print(f"agent run failed: {detail}", file=sys.stderr)
            return 1
        if _agent_error_is_terminal(stats, timed_out=timed_out):
            if str(stats.get("subtype") or "") == "error_max_turns":
                # Budget exhaustion is a pass@1 quality outcome, not an
                # infrastructure failure: freeze and let the evaluator grade
                # whatever the agent produced within its budget.
                terminal_reason = (
                    f"turn budget ({args.max_turns}) exhausted; the workspace was frozen as-is"
                )
            else:
                print(f"agent reported an error: {stats.get('result') or stats}", file=sys.stderr)
                return 1
        reported_turns = stats.get("num_turns")
        if (
            args.agent == "claude-code"
            and terminal_reason is None
            and isinstance(reported_turns, int | float)
            and reported_turns > args.max_turns
        ):
            terminal_reason = (
                f"Claude CLI reported successful completion after {int(reported_turns)} turns, "
                f"exceeding the requested {args.max_turns}-turn limit; the workspace was "
                "frozen as-is and the overrun is disclosed"
            )

        pristine = {
            path.relative_to(source).as_posix(): path.read_bytes()
            for path in sorted(source.rglob("*"))
            if path.is_file()
        }
        added: list[str] = []
        modified: list[str] = []
        for path in sorted(workspace.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(workspace)
            if _excluded(relative):
                continue
            key = relative.as_posix()
            if key not in pristine:
                added.append(key)
            elif path.read_bytes() != pristine[key]:
                modified.append(key)

        overlay = out_dir / "overlay"
        if overlay.exists():
            shutil.rmtree(overlay)
        for key in added:
            destination = overlay / key
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(workspace / key, destination)

        if not added:
            turns = stats.get("num_turns")
            print(
                "agent produced no new files; refusing to freeze an empty candidate "
                f"(terminal: {terminal_reason or 'completed'}; "
                f"turns: {turns if turns is not None else 'none recorded'}). "
                "No error event plus no recorded activity is the signature of a "
                "silent provider failure - classify it in the infrastructure "
                "ledger instead of charging it as an agent-quality result.",
                file=sys.stderr,
            )
            return 3
        _write_candidate(out_dir, args, agent_version, stats)
        _write_disclosure(
            out_dir,
            args,
            agent_version=agent_version,
            prompt=prompt,
            stats=stats,
            added=added,
            modified=modified,
            readiness_context=readiness_context,
            terminal_reason=terminal_reason,
        )
    print(
        f"{args.candidate_id}: {len(added)} file(s) in overlay"
        + (f", {len(modified)} contract-violating modification(s) DROPPED" if modified else "")
        + (f", {stats.get('num_turns', '?')} turns" if stats else "")
        + (f" [{terminal_reason}]" if terminal_reason else "")
    )
    return 0


PROVIDER_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "deepinfra": "https://api.deepinfra.com/v1/openai",
    "fireworks": "https://api.fireworks.ai/inference/v1",
    "together": "https://api.together.xyz/v1",
}
PROVIDER_ENV_KEYS = {
    "openai": "OPENAI_API_KEY",
    "deepinfra": "DEEPINFRA_API_KEY",
    "fireworks": "FIREWORKS_API_KEY",
    "together": "TOGETHER_API_KEY",
}


def _codex_command(args: argparse.Namespace, prompt: str, codex_home: Path) -> list[str]:
    codex_home.mkdir(parents=True, exist_ok=True)
    # The isolated CODEX_HOME has no login session, so every provider —
    # OpenAI included — authenticates through an env-var API key declared on
    # a custom model_providers entry. Codex CLI >= 0.150 refuses
    # `wire_api = "chat"` outright, so every provider speaks the responses
    # wire API; it also reserves the built-in `openai` provider id (and the
    # built-in provider sends no bearer from a loginless CODEX_HOME), so the
    # OpenAI entry is registered as `openai-custom` against the same base URL.
    provider_id = "openai-custom" if args.provider == "openai" else args.provider
    config = (
        f'preferred_auth_method = "apikey"\n'
        f"[model_providers.{provider_id}]\n"
        f'name = "{provider_id}"\n'
        f'base_url = "{PROVIDER_BASE_URLS[args.provider]}"\n'
        f'env_key = "{PROVIDER_ENV_KEYS[args.provider]}"\n'
        f'wire_api = "responses"\n'
    )
    (codex_home / "config.toml").write_text(config, encoding="utf-8")
    command = [
        args.agent_bin,
        "exec",
        "--model",
        args.model,
        "--json",
        "--skip-git-repo-check",
        "--dangerously-bypass-approvals-and-sandbox",
    ]
    command += ["--config", f'model_provider="{provider_id}"']
    command.append(prompt)
    return command


def _codex_stats(stdout: str, args: argparse.Namespace, measured_ms: float) -> dict[str, object]:
    turns = 0
    input_tokens = 0
    cached_input_tokens = 0
    output_tokens = 0
    terminal_kind: str | None = None
    error_events = 0
    last_error: str | None = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        kind = str(event.get("type") or event.get("msg", {}).get("type") or "")
        if kind == "turn.completed":
            turns += 1
            terminal_kind = kind
        elif kind == "turn.failed":
            terminal_kind = kind
            error_events += 1
            last_error = json.dumps(event)[:500]
        elif kind == "error":
            # Codex emits top-level error events while it reconnects. A later
            # turn.completed is authoritative proof that the retry recovered.
            # Keep the notice for diagnostics, but do not poison the result.
            error_events += 1
            last_error = json.dumps(event)[:500]
        usage = _find_usage(event)
        if usage:
            input_tokens = max(input_tokens, int(usage.get("input_tokens") or 0)) or input_tokens
            cached_input_tokens = (
                max(cached_input_tokens, int(usage.get("cached_input_tokens") or 0))
                or cached_input_tokens
            )
            output_tokens = (
                max(output_tokens, int(usage.get("output_tokens") or 0)) or output_tokens
            )
    is_error = terminal_kind != "turn.completed"
    subtype = "codex-exec"
    if terminal_kind == "turn.failed":
        subtype = "codex-turn-failed"
    elif terminal_kind is None:
        subtype = "codex-no-terminal-event"
        if last_error is None:
            last_error = "Codex transcript ended without turn.completed or turn.failed"
    cost: float | None = None
    basis = "measured wall-clock; token usage unavailable"
    if input_tokens or output_tokens:
        basis = f"computed from token usage ({input_tokens} in / {output_tokens} out)"
        if args.price_in is not None and args.price_out is not None:
            cost = (input_tokens * args.price_in + output_tokens * args.price_out) / 1_000_000
            basis += f" at ${args.price_in}/M in, ${args.price_out}/M out"
    stats: dict[str, object] = {
        "num_turns": turns or None,
        "duration_ms": measured_ms,
        "total_cost_usd": cost,
        "is_error": is_error,
        "subtype": subtype,
        "result": last_error,
        "cost_basis": basis,
        "input_tokens": input_tokens or None,
        "cached_input_tokens": cached_input_tokens or None,
        "output_tokens": output_tokens or None,
        "recovered_error_events": error_events if terminal_kind == "turn.completed" else 0,
        "terminal_event": terminal_kind,
    }
    return stats


def _find_usage(event: dict) -> dict | None:
    for key in ("usage", "token_usage"):
        value = event.get(key)
        if isinstance(value, dict):
            return value
    info = event.get("info") or event.get("msg") or {}
    if isinstance(info, dict):
        for key in ("usage", "token_usage", "total_token_usage"):
            value = info.get(key)
            if isinstance(value, dict):
                return value
    return None


def _excluded(relative: Path) -> bool:
    if any(part in EXCLUDED_PARTS for part in relative.parts):
        return True
    if relative.suffix in EXCLUDED_SUFFIXES:
        return True
    return relative.name in EXCLUDED_NAMES


def _as_text(value: object) -> str:
    """TimeoutExpired carries bytes on POSIX even in text mode; normalize."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _agent_error_is_terminal(stats: dict[str, object], *, timed_out: bool) -> bool:
    if not stats.get("is_error"):
        return False
    # A killed Codex process necessarily lacks a terminal JSONL event. Timeout
    # is already disclosed as the binding budget; freeze any non-empty work so
    # it can be graded instead of misclassifying budget exhaustion as provider
    # infrastructure. A real turn.failed remains terminal even at the deadline.
    return not (timed_out and stats.get("subtype") == "codex-no-terminal-event")


def _agent_stats(stdout: str) -> dict[str, object]:
    for line in reversed([line for line in stdout.splitlines() if line.strip()]):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and "num_turns" in payload:
            return {
                key: payload.get(key)
                for key in (
                    "num_turns",
                    "duration_ms",
                    "total_cost_usd",
                    "is_error",
                    "subtype",
                    "result",
                )
            }
    return {}


def _write_candidate(
    out_dir: Path, args: argparse.Namespace, agent_version: str, stats: dict[str, object]
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "schema_version: sanka-bench/candidate/v0.2",
        f"id: {args.candidate_id}",
        "kind: overlay",
        "overlay: overlay",
        "provenance:",
        f"  producer: {args.agent}",
        f"  revision: {args.model} via {agent_version or 'claude cli'}",
        f"  provider_variant: {args.provider_variant}",
        "  command: scripts/run_agent_candidate.py (prompt and budget in GENERATED.md)",
    ]
    duration = stats.get("duration_ms")
    cost = stats.get("total_cost_usd")
    turns = stats.get("num_turns")
    if any(isinstance(value, int | float) for value in (duration, cost, turns)):
        lines.append("stats:")
        if isinstance(turns, int | float):
            lines.append(f"  turns: {int(turns)}")
        if isinstance(duration, int | float):
            lines.append(f"  duration_seconds: {round(duration / 1000, 1)}")
        if isinstance(cost, int | float):
            lines.append(f"  cost_usd: {round(float(cost), 4)}")
    (out_dir / "candidate.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_disclosure(
    out_dir: Path,
    args: argparse.Namespace,
    *,
    agent_version: str,
    prompt: str,
    stats: dict[str, object],
    added: list[str],
    modified: list[str],
    readiness_context: dict[str, object] | None,
    terminal_reason: str | None = None,
) -> None:
    duration = stats.get("duration_ms")
    minutes = f"{int(duration) / 60000:.1f} min" if isinstance(duration, int | float) else "unknown"
    cost = stats.get("total_cost_usd")
    cost_text = f"${float(cost):.2f}" if isinstance(cost, int | float) else "unknown"
    if args.agent == "claude-code":
        budget_text = str(args.max_turns)
    else:
        budget_text = (
            f"{args.max_turns} requested - not enforced by Codex CLI; "
            "the 3600s wall-clock timeout is the binding limit"
        )
    modified_text = (
        "\n".join(f"- `{name}`" for name in modified)
        if modified
        else "none — the add-only contract was respected"
    )
    attempt_text = str(args.attempt)
    if args.prior_failure:
        attempt_text += (
            f" (previous attempt failed on infrastructure, not agent quality: {args.prior_failure})"
        )
    elif args.attempt == 1:
        attempt_text += " (pass@1; no retries)"
    agent_label = "Claude Code" if args.agent == "claude-code" else "Codex CLI"
    provider = "anthropic" if args.agent == "claude-code" else args.provider
    version = agent_version or args.agent_bin
    readiness_value = "not run"
    readiness_section = ""
    if readiness_context is not None:
        readiness_value = (
            f"{float(readiness_context['readiness']) * 100:.1f}% → {readiness_context['decision']}"
        )
        readiness_section = (
            "\n## Sanka readiness preflight\n\n"
            "The machine-readable preflight is preserved in "
            "`sanka-readiness.json`. Its threshold decision was made before the "
            "agent started; the official v0.2 score remains unchanged.\n"
        )
    (out_dir / "GENERATED.md").write_text(
        f"""# Coding-agent baseline provenance: {args.candidate_id}

Produced unattended by `scripts/run_agent_candidate.py` — no human
intervention between prompt and frozen overlay.

| Disclosure | Value |
|---|---|
| Agent | {agent_label} (`{version}`) |
| Provider | {provider} |
| Provider variant | {args.provider_variant} |
| Recovered transport notices | {stats.get("recovered_error_events", 0)} |
| Cost basis | {stats.get("cost_basis", "agent-reported")} |
| Model | `{args.model}` |
| Turn budget | {budget_text} |
| Turns used | {stats.get("num_turns", "unknown")} |
| Duration | {minutes} |
| Reported cost | {cost_text} |
| Terminal | {terminal_reason or "completed within budget"} |
| Attempt | {attempt_text} |
| Sanka readiness preflight | {readiness_value} |

Files added by the agent: {len(added)}. Contract-violating modifications to
existing source files (dropped from the overlay, since candidates are
add-only):
{modified_text}
{readiness_section}

## Prompt (verbatim)

```
{prompt}
```
""",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
