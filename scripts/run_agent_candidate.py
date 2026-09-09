"""Produce a frozen coding-agent candidate for one benchmark task.

Runs a command-line coding agent headlessly against a pristine copy of the
task's source with a fixed migration prompt, collects every file the agent
added as the candidate overlay, and writes the candidate with full
disclosure: model, tool version, prompt verbatim, turn budget, turns used,
duration, and reported cost. The agent runs unattended — no human
intervention — and the frozen overlay is then graded by the ordinary
tool-neutral evaluator like any other candidate.

Use --sanka-workflow artifacts-first-v1 to prepare and install generated artifacts
before either official Sanka arm starts. The default availability-v1 preserves
historical runs; every treatment still uses the same evaluator.

Three official configurations and one separate diagnostic arm:

- ``--candidate-id claude-code-alone`` — the agent and the task, nothing else;
- ``--candidate-id claude-code-sanka-cli`` (with ``--sanka-bin``) — the same
  agent and prompt plus the Sanka CLI, without installing its coding-agent skill;
- ``--candidate-id claude-code-with-sanka`` (with ``--sanka-bin``) — the same
  agent, same budget, same contract, and CLI, plus the project-local Sanka skill.
- ``--candidate-id claude-code-with-sanka-readiness-aware`` — the harness runs
  scan/plan first, generates a scaffold only at or above the configured native
  readiness threshold, and otherwise sends the agent the readiness number and
  the verifier command only (the route gap inventory is frozen in
  ``sanka-readiness.json``, not sent). This arm is diagnostic and never
  replaces the official pass@1 configurations.

Three agent families share the same contract, prompt, and freezing logic:

- ``--agent sanka-native`` (default) owns the Sanka lifecycle and calls direct
  OpenAI Responses or Fireworks Chat APIs only for remaining work;
- ``--agent claude-code`` drives the Claude CLI headlessly and uses
  its self-reported turns, duration, and cost;
- ``--agent codex`` drives OpenAI's Codex CLI (``codex exec``) against the
  OpenAI API or any OpenAI-compatible provider (``--provider deepinfra``,
  ``fireworks``, ``together``). Codex does not self-report dollar cost, so the
  run records measured wall-clock and token usage, and computes cost from the
  per-model prices passed via ``--price-in``/``--price-out`` (USD per million
  tokens) — the disclosure names that basis explicitly.

Candidate ids use lowercase letters, digits and hyphens (``<agent>-<model-slug>-alone`` /
``...-sanka-cli`` / ``...-with-sanka`` / ``...-with-sanka-readiness-aware``); the suffix selects
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
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path

from sanka_bench import agent_isolation, native_agent
from sanka_bench.environment import isolated_environment
from sanka_bench.hashing import digest_tree
from sanka_bench.schema import load_and_validate, validate_candidate_id

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
   identical snapshots, repeats runs, and rejects nondeterminism.
   {grading_scope}
   Match the source application's semantics, including headers, error wording,
   and validation. The source is the specification.
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

Execution budget: {max_turns} tool-use turns and {wall_seconds} seconds.
Create a bootable target_app.py and serving settings early, within roughly
the first sixth of your turn budget. Spend the middle two thirds implementing
and comparing behavior, then reserve the remainder for verification and repairs.
Improve a running candidate; do not postpone implementation until you have
investigated every possible edge case. Leave the best runnable candidate at
the budget limit. Keep scratch work in the workspace or $TMPDIR.
Local file generation inside this disposable workspace is authorized. No
external destination writes, production changes, or package installations are
part of this task. Only the copied source, public tests and supplied tools are
available; evaluator files and other runs are outside the agent's sandbox.
"""

PROMPT_SANKA = """
The Sanka migration CLI at {sanka} is available.
Pass `--extension-env PYTHONPATH` to Sanka lifecycle commands so its isolated
extension process can import the benchmark fixture dependencies.
"""

PROMPT_SANKA_SKILL = """
A project-local `sanka-cli` skill is installed in this workspace and is
available to use.
"""


def _inline_skill(record: dict[str, str]) -> str:
    """Deliver exactly the pinned installed content, with auditable exposure."""
    content = (Path(record["path"]) / "SKILL.md").read_bytes()
    if hashlib.sha256(content).hexdigest() != record["content_sha256"]:
        raise RuntimeError("Sanka skill changed after installation")
    record["delivery"] = "inline-prompt-v1"
    return "\nThe following installed Sanka Skill applies to this migration:\n\n" + content.decode()


VERIFIER_COMMAND = (
    "{sanka} verify . --to fastapi --scenarios public-tests/scenarios.json "
    "--candidate . --entrypoint target_app.py --db-env BENCH_DB_PATH --edge-probes "
    "--extension-env PYTHONPATH --json"
)

PROMPT_VERIFIER = """
Sanka also ships the differential verifier. Run it whenever you want to know
where the candidate still diverges, and before you finish:

    {verifier}

It replays every public scenario, plus edge probes derived from the source's
own routes (OPTIONS/Allow, an unsupported method, the slash variant, a
missing-object request), against the original application and target_app.py
on identical fresh databases, and reports every status, body, header, and
table-content difference together with the route class that served each
request. Scenarios that assume existing rows can be replayed from a seed script
with `--seed <file.py>` (Django is configured when it runs). The verifier never
sees the hidden grading set; a clean run is necessary, not sufficient. Its JSON
output is the whole contract: read that, not the CLI's installation.
"""

PROMPT_SANKA_READINESS = """
The Sanka migration CLI preflight has already scanned and planned this source.
Native readiness is {readiness_percent:.1f}% ({native_routes}/{eligible_routes}
non-alias routes) against a {threshold_percent:.1f}% scaffold threshold.
Plan hash: {plan_hash}

{decision}
{notes}{verifier}"""

PARITY_NOTES_FILE = "sanka-parity-notes.md"

PROMPT_PARITY_NOTES = """
Sanka's scan also wrote per-route parity notes — the source's exact
authentication order and error strings, pagination, ordering, file, uniqueness,
and validation-message behavior, derived from the running application — to
{notes_file} ({note_count} notes over {route_count} routes). Read a route's
section before implementing it.
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
EXCLUDED_NAMES = {".DS_Store", "AGENT_TASK.md", "CLAUDE.md", PARITY_NOTES_FILE}


_SAMPLE_SUFFIX = re.compile(r"-s\d+$")


def task_prompt(task_dir: Path, max_turns: int, wall_seconds: int) -> str:
    task = load_and_validate(task_dir / "task.yaml", "task")
    graded = (task_dir / task["evaluation"]["scenarios"]).resolve()
    public = (task_dir / "public-tests" / "scenarios.json").resolve()
    scope = (
        "The public scenarios are a representative sample; grading uses a hidden superset."
        if graded != public
        else "This task grades the supplied public scenarios."
    )
    core = PROMPT_CORE
    if task["target"]["framework"] == "flask":
        core = core.replace("FastAPI", "Flask").replace("fastapi", "flask")
        core = core.replace("Flask `APIRoute`", "Flask URL rule")
        core = core.replace("vs flask TestClient", "vs Flask test_client")
    return core.format(
        python=sys.executable, grading_scope=scope, max_turns=max_turns, wall_seconds=wall_seconds
    )


def _candidate_mode(candidate_id: str) -> str | None:
    """Arm selected by the candidate id, ignoring a trailing ``-s<k>`` sample suffix."""
    family = _SAMPLE_SUFFIX.sub("", candidate_id)
    if family.endswith("-with-sanka-readiness-aware"):
        return "readiness-aware"
    if family.endswith("-with-sanka"):
        return "with-sanka"
    if family.endswith("-sanka-cli"):
        return "sanka-cli"
    if family.endswith("-alone"):
        return "alone"
    return None


def _readiness_context(
    plan: dict[str, object],
    threshold: float,
    scan: dict[str, object] | None = None,
    *,
    partial_scaffold: bool = False,
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
        if not reasons:
            reasons = [
                {"message": reason}
                for reason in item.get("reasons") or []
                if isinstance(reason, str)
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
        if partial_scaffold or (native_routes > 0 and readiness >= threshold)
        else "gap-report-only",
        "partial_scaffold": partial_scaffold,
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


def _verifier_prompt(sanka: Path, framework: str = "fastapi") -> str:
    command = VERIFIER_COMMAND.format(sanka=sanka).replace("--to fastapi", f"--to {framework}")
    return PROMPT_VERIFIER.format(verifier=command)


def _readiness_prompt(context: dict[str, object], sanka: Path) -> str:
    """Readiness number, threshold decision, verifier command — and nothing else.

    Route and critic checklists sent without capability raise cost without
    changing verdicts. The unsupported and unscanned route inventory stays in
    ``sanka-readiness.json`` for the record; the agent gets the tool instead.
    """
    if context["decision"] == "emit-scaffold":
        decision = (
            "The harness generated `bench-candidate/overlay/`. Copy its new files "
            "to the repository root, including non-Python artifacts. Keep existing "
            "source files unchanged when names overlap. Then "
            "adapt the routes the plan marks as needing manual work "
            "(`.sanka/plan-fastapi.json` lists each with its reasons)."
        )
        if context.get("installed_files"):
            decision = (
                "The harness already installed the new generated scaffold files in the "
                "repository root. Reuse and repair them; do not regenerate the migration. "
                "Original source files were preserved. Check the source behavior and public "
                "scenarios, complete any missing native behavior, then run the verifier below. "
                "A generated scaffold is a starting point, not evidence of correctness."
            )
        if context.get("partial_scaffold"):
            decision += (
                " Partial generation was explicitly selected, regardless of readiness. "
                "Unconverted routes remain manual gaps; generated files do not imply parity."
            )
    else:
        decision = (
            "The harness intentionally did not generate a scaffold because readiness "
            "is below the threshold. Do not run `sanka apply`; implement the native "
            "FastAPI target from the source."
        )
    framework = str(context.get("target_framework", "fastapi"))
    replay_supported = framework == "fastapi" or "verify" in context.get("extension_commands", [])
    if framework == "flask":
        decision = decision.replace("FastAPI", "Flask").replace("plan-fastapi", "plan-flask")
        if not replay_supported:
            decision = decision.replace(
                "run the verifier below", "compare source and candidate in local tests"
            )
    return PROMPT_SANKA_READINESS.format(
        readiness_percent=float(context["readiness"]) * 100,
        native_routes=context["native_routes"],
        eligible_routes=context["native_eligible_routes"],
        threshold_percent=float(context["threshold"]) * 100,
        plan_hash=context["plan_hash"],
        decision=decision,
        notes=_notes_prompt(context),
        verifier=_verifier_prompt(sanka, framework)
        if replay_supported
        else (
            "The Flask extension does not yet provide differential replay. Use source and "
            "Flask test clients with identical fixtures and the public scenarios.\n"
        ),
    )


def _notes_prompt(context: dict[str, object]) -> str:
    """One pointer to the notes file when the plan carried notes; nothing otherwise."""
    count = int(context.get("parity_note_count") or 0)
    notes_file = context.get("parity_notes_file")
    if not count or not notes_file:
        return ""
    return PROMPT_PARITY_NOTES.format(
        notes_file=notes_file,
        note_count=count,
        route_count=int(context.get("parity_note_routes") or 0),
    )


def _write_parity_notes(
    workspace: Path, plan: dict[str, object], context: dict[str, object]
) -> Path | None:
    """Render the plan's per-route parity notes for the agent, grouped by route.

    Notes are facts about the source application (M2 of the fresh-start program), not
    instructions; they cover the routes the agent has to write by hand — every non-alias
    route below the scaffold threshold, only the non-generated ones above it. Plans
    from older engines carry no notes, and then nothing is written.
    """
    sections: list[str] = []
    note_count = 0
    scaffolded = context.get("decision") == "emit-scaffold"
    for item in plan.get("routes") or []:
        if not isinstance(item, dict):
            continue
        if item.get("strategy") == "dropped-format-suffix-alias":
            continue
        if scaffolded and item.get("automatic") is True:
            continue
        notes = [note for note in item.get("parity_notes") or [] if isinstance(note, dict)]
        if not notes:
            continue
        lines = [f"## {item.get('method')} {item.get('path')}", ""]
        for note in notes:
            source = f" ({note.get('source')})" if note.get("source") else ""
            lines.append(f"- [{note.get('family')}] {note.get('message')}{source}")
        lines.append("")
        sections.append("\n".join(lines))
        note_count += len(notes)
    if not sections:
        return None
    header = [
        "# Parity notes from the Sanka scan",
        "",
        "Facts about the source application's exact behavior, derived from its running",
        "Django/DRF classes by `sanka scan`. One section per route you have to write;",
        "the original application remains the specification and the differential",
        "verifier remains the check.",
        "",
    ]
    path = workspace / PARITY_NOTES_FILE
    path.write_text("\n".join(header) + "\n" + "\n".join(sections), encoding="utf-8")
    context["parity_notes_file"] = PARITY_NOTES_FILE
    context["parity_note_count"] = note_count
    context["parity_note_routes"] = len(sections)
    return path


def _run_sanka_command(
    command: list[str],
    *,
    workspace: Path,
    env: dict[str, str],
    tolerate: tuple[str, ...] = (),
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
    if outcome.returncode != 0 and not any(code in outcome.stdout for code in tolerate):
        detail = outcome.stderr.strip() or outcome.stdout.strip() or "no output"
        raise RuntimeError(f"Sanka preflight failed ({' '.join(command[:2])}): {detail[:2000]}")
    return outcome


OFFICIAL_MARKETPLACE = "https://github.com/sankaHQ/extensions.git"
DRF_EXTENSION_ID = "sanka/drf-to-fastapi"
# sanka-cli 0.2.0 asks for these interactively; a headless plan must pass them.
PLAN_INPUTS = (
    "--strategy",
    "native",
    "--generation",
    "minimal",
    "--package-manager",
    "uv",
    "--output",
    ".sanka/output/fastapi",
)


def _enable_sanka_extension(
    sanka_bin: Path, *, workspace: Path, env: dict[str, str], framework: str = "fastapi"
) -> list[str]:
    """Make the DRF extension usable in the workspace: marketplace snapshot + project lock.

    sanka-cli resolves extensions through a trusted marketplace snapshot in SANKA_HOME
    and a per-project lock; neither exists in a fresh workspace. Installing the tool is
    part of offering it, so both with-Sanka arms get this before the agent starts and
    the alone arm never sees it. The marketplace add is idempotent by name.
    """
    _run_sanka_command(
        [str(sanka_bin), "extension", "marketplace", "add", OFFICIAL_MARKETPLACE, "--json"],
        workspace=workspace,
        env=env,
        tolerate=("SANKA_MARKETPLACE_EXISTS",),
    )
    enabled = _run_sanka_command(
        [str(sanka_bin), "extension", "add", f"sanka/drf-to-{framework}", "--json"],
        workspace=workspace,
        env=env,
    )

    records = _cli_data(enabled.stdout).get("records")
    for record in records if isinstance(records, list) else []:
        if isinstance(record, dict) and record.get("id") == f"sanka/drf-to-{framework}":
            commands = record.get("commands")
            if isinstance(commands, list) and all(isinstance(item, str) for item in commands):
                return commands
    return []


def install_sanka_skill(
    sanka_bin: Path,
    workspace: Path,
    env: dict[str, str],
    pinned_sha256: str | None = None,
) -> dict[str, str]:
    outcome = _run_sanka_command(
        [
            str(sanka_bin),
            "--output",
            "json",
            "skill",
            "install",
            "claude",
            "--scope",
            "project",
            "--project-dir",
            str(workspace),
        ],
        workspace=workspace,
        env=env,
    )
    try:
        payload = json.loads(outcome.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Sanka skill installer returned invalid JSON") from exc
    installations = payload.get("installations") if isinstance(payload, dict) else None
    if (
        not isinstance(payload, dict)
        or payload.get("skill") != "sanka-cli"
        or payload.get("scope") != "project"
        or not isinstance(installations, list)
        or len(installations) != 1
        or not isinstance(installations[0], dict)
        or installations[0].get("harness") != "claude"
    ):
        raise RuntimeError("Sanka skill installer returned an unexpected installation record")
    installation = installations[0]
    target = Path(str(installation.get("path") or "")).resolve()
    expected = workspace.resolve() / ".claude" / "skills" / "sanka-cli"
    if target != expected or not target.is_relative_to(workspace.resolve()):
        raise RuntimeError(f"Sanka skill path escaped the workspace: {target}")
    skill_file = target / "SKILL.md"
    expected_digest = str(payload.get("content_sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_digest) or not skill_file.is_file():
        raise RuntimeError("Sanka skill installation is incomplete")
    actual_digest = hashlib.sha256(skill_file.read_bytes()).hexdigest()
    if actual_digest != expected_digest:
        raise RuntimeError(
            f"Sanka skill digest mismatch: expected {expected_digest}, got {actual_digest}"
        )
    if pinned_sha256 and actual_digest != pinned_sha256.removeprefix("sha256:"):
        raise RuntimeError("installed Sanka skill does not match the pinned manifest digest")
    return {
        "scope": "project",
        "path": str(target),
        "status": str(installation.get("status") or ""),
        "content_sha256": actual_digest,
    }


def _cli_data(stdout: str) -> dict[str, object]:
    """The `data` object of a sanka-cli JSON response, or {} when there is none."""
    try:
        payload = json.loads(stdout) if stdout.strip() else {}
    except json.JSONDecodeError:
        return {}
    data = payload.get("data") if isinstance(payload, dict) else None
    return data if isinstance(data, dict) else {}


def _sanka_artifact(stdout: str, name: str, workspace: Path, framework: str = "fastapi") -> Path:
    """Locate a lifecycle artifact from the CLI's JSON output, else the legacy `.sanka/` spot.

    sanka-cli 0.2.0 keeps each extension's artifacts under
    `.sanka/extensions/<extension id>/` and lists them in the response's `artifacts`;
    older engines wrote them straight into `.sanka/`.
    """
    try:
        payload = json.loads(stdout) if stdout.strip() else {}
    except json.JSONDecodeError:
        payload = {}
    listed = payload.get("artifacts") if isinstance(payload, dict) else None
    for raw in listed or []:
        if isinstance(raw, str) and Path(raw).name == name:
            candidate = (workspace / raw).resolve()
            if not candidate.is_relative_to(workspace.resolve()):
                raise RuntimeError(f"Sanka artifact escapes workspace: {name}")
            return candidate
    for candidate in (
        workspace / ".sanka" / "extensions" / "sanka" / f"drf-to-{framework}" / name,
        workspace / ".sanka" / name,
    ):
        if candidate.is_file():
            if not candidate.resolve().is_relative_to(workspace.resolve()):
                raise RuntimeError(f"Sanka artifact escapes workspace: {name}")
            return candidate
    raise RuntimeError(f"Sanka did not produce {name}; artifacts listed: {listed!r}")


def _sanka_tool_versions(sanka_bin: Path, *, workspace: Path, env: dict[str, str]) -> str:
    """`sanka --version` plus the locked DRF extension version, for GENERATED.md."""
    version = subprocess.run(
        [str(sanka_bin), "--version"], capture_output=True, text=True, check=False, env=env
    ).stdout.strip()
    extension = ""
    listed = subprocess.run(
        [str(sanka_bin), "extension", "list", "--json"],
        cwd=workspace,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        records = json.loads(listed.stdout).get("data", {}).get("records", [])
    except (json.JSONDecodeError, AttributeError):
        records = []
    for record in records:
        if isinstance(record, dict) and record.get("id") in {
            DRF_EXTENSION_ID,
            "sanka/drf-to-flask",
        }:
            extension += f"; {record.get('id')} {record.get('version')} {record.get('status')}"
    return f"{version or sanka_bin}{extension}"


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
    framework: str = "fastapi",
    partial_scaffold: bool = False,
) -> dict[str, object]:
    commands = _enable_sanka_extension(sanka_bin, workspace=workspace, env=env, framework=framework)
    scanned = _run_sanka_command(
        [str(sanka_bin), "scan", ".", "--extension-env", "PYTHONPATH", "--json"],
        workspace=workspace,
        env=env,
    )
    planned = _run_sanka_command(
        [
            str(sanka_bin),
            "plan",
            ".",
            "--to",
            framework,
            *PLAN_INPUTS[:-1],
            f".sanka/output/{framework}",
            "--extension-env",
            "PYTHONPATH",
            "--json",
        ],
        workspace=workspace,
        env=env,
    )
    plan_path = _sanka_artifact(planned.stdout, f"plan-{framework}.json", workspace, framework)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if not isinstance(plan, dict):
        raise RuntimeError(f"Sanka plan is not an object: {plan_path}")
    scan_path = _sanka_artifact(scanned.stdout, "scan.json", workspace, framework)
    scan = json.loads(scan_path.read_text(encoding="utf-8"))
    if not isinstance(scan, dict):
        raise RuntimeError(f"Sanka scan is not an object: {scan_path}")
    context = _readiness_context(
        plan, threshold, scan, partial_scaffold=partial_scaffold and framework == "flask"
    )
    context["target_framework"] = framework
    context["extension_commands"] = commands
    # sanka-cli reviews the core plan (which wraps the extension plan); apply wants the
    # core hash from the CLI response. Older engines had a single hash: fall back to it.
    context["core_plan_hash"] = _cli_data(planned.stdout).get("plan_hash") or context["plan_hash"]
    if context["decision"] == "emit-scaffold":
        _run_sanka_command(
            [
                str(sanka_bin),
                "apply",
                "--root",
                ".",
                "--plan-hash",
                str(context["core_plan_hash"]),
                "--bench-candidate",
                "./bench-candidate",
                "--extension-env",
                "PYTHONPATH",
                "--json",
            ],
            workspace=workspace,
            env=env,
        )
    # Written only after apply: sanka fingerprints the workspace when it reviews the
    # plan and refuses to apply once any file changed, and this file is one.
    _write_parity_notes(workspace, plan, context)
    return context


def _observed_work(stdout: str) -> dict[str, int | None]:
    """Count unique response/tool IDs; streaming chunks are not extra model calls."""
    responses: set[str] = set()
    calls: set[str] = set()
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != "assistant":
            continue
        message = event.get("message")
        if not isinstance(message, dict):
            continue
        if isinstance(message.get("id"), str):
            responses.add(message["id"])
        content = message.get("content")
        for block in content if isinstance(content, list) else []:
            if (
                isinstance(block, dict)
                and block.get("type") == "tool_use"
                and isinstance(block.get("id"), str)
            ):
                calls.add(block["id"])
    return {
        "observed_model_responses": len(responses) if responses else None,
        "tool_calls": len(calls) if responses else None,
        "provider_api_requests": None,
        "provider_retries": None,
    }


def _workspace_files(workspace: Path) -> dict[str, str]:
    return {
        path.relative_to(workspace).as_posix(): _sha256_bytes(path.read_bytes())
        for path in sorted(workspace.rglob("*"))
        if path.is_file() and not _excluded(path.relative_to(workspace))
    }


def _promote_scaffold(workspace: Path, overlay: Path | None = None) -> dict[str, str]:
    """Install only new generated files, preserving the immutable source contract."""
    overlay = overlay if overlay is not None else workspace / "bench-candidate" / "overlay"
    if (
        not overlay.is_dir()
        or overlay.is_symlink()
        or not overlay.resolve().is_relative_to(workspace.resolve())
    ):
        raise RuntimeError("Sanka did not produce a scaffold overlay")
    files = {}
    for path in sorted(overlay.rglob("*")):
        relative = path.relative_to(overlay)
        destination = workspace / relative
        if path.is_symlink() or not path.resolve().is_relative_to(overlay.resolve()):
            raise RuntimeError(f"Unsafe generated artifact: {relative}")
        if not path.is_file() or _excluded(relative):
            continue
        if not destination.resolve().is_relative_to(workspace.resolve()):
            raise RuntimeError(f"Unsafe scaffold destination: {relative}")
        if destination.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        files[relative.as_posix()] = _sha256_bytes(path.read_bytes())
    if not files:
        raise RuntimeError("Sanka scaffold contains no usable new files")
    return files


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument(
        "--candidate-id",
        required=True,
        help="<agent>-<model-slug>-alone or ...-with-sanka",
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--sandbox", type=Path)
    parser.add_argument(
        "--agent", default="sanka-native", choices=("sanka-native", "claude-code", "codex")
    )
    parser.add_argument("--agent-bin", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--actual-model-id", default=None)
    parser.add_argument(
        "--reasoning-effort", choices=("none", "low", "medium", "high", "xhigh", "max")
    )
    parser.add_argument("--route-kind", default="legacy")
    parser.add_argument("--billing-mode", default="unknown")
    parser.add_argument("--subscription-bin", type=Path)
    parser.add_argument("--gateway-profile", default=None)
    parser.add_argument(
        "--provider",
        default=None,
        help="actual serving provider disclosed by this treatment",
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
        help="USD per million input tokens (native: uncached upper rate including cache writes)",
    )
    parser.add_argument(
        "--price-out",
        type=float,
        default=None,
        help="USD per million output tokens, for computed cost",
    )
    parser.add_argument(
        "--price-cached",
        type=float,
        help="native USD per million reported cache-read tokens; omitted uses price-in",
    )
    parser.add_argument("--max-turns", type=int, default=60)
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        help="native per-response token limit, including reasoning (default: 8192)",
    )
    parser.add_argument(
        "--max-context-bytes",
        type=int,
        help="native serialized request context limit (default: 120000 bytes)",
    )
    parser.add_argument(
        "--max-agent-cost-usd",
        type=float,
        help="estimated-cost cap (native requires prices); not verified provider billing",
    )
    parser.add_argument("--wall-clock-seconds", type=int, default=3600)
    parser.add_argument("--sanka-bin", type=Path, default=None)
    parser.add_argument("--sanka-skill-sha256")
    parser.add_argument(
        "--sanka-workflow",
        choices=(
            "availability-v1",
            "artifacts-first-v1",
            "artifacts-first-v2",
            "native-lifecycle-v1",
        ),
        default="availability-v1",
    )
    parser.add_argument(
        "--sanka-readiness-threshold",
        type=float,
        default=0.5,
        help="minimum native readiness for artifacts-first and diagnostic scaffolds",
    )
    parser.add_argument("--attempt", type=int, default=1)
    parser.add_argument(
        "--prior-failure",
        default=None,
        help="disclosed reason the previous attempt failed (infrastructure retries only)",
    )
    args = parser.parse_args()

    if args.model is None:
        if args.agent == "sanka-native":
            parser.error("--model must name the exact provider model")
        args.model = "claude-sonnet-5"
    if args.provider is None:
        args.provider = "anthropic" if args.agent == "claude-code" else "openai"
    subscription_run = (
        args.agent == "sanka-native"
        and args.provider == "openai"
        and args.billing_mode == "subscription"
    )
    if (
        args.agent in {"codex", "sanka-native"}
        and args.billing_mode not in {"unknown", "api_key"}
        and not subscription_run
    ):
        parser.error(
            "this generation adapter requires API-key billing; sanka-bench login stores a "
            "subscription session but subscription generation is not yet supported"
        )
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", args.provider_variant):
        print(
            "--provider-variant must be a slug containing only letters, digits, '.', '_' or '-'",
            file=sys.stderr,
        )
        return 2
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", args.provider):
        print("--provider must be a slug", file=sys.stderr)
        return 2
    if args.agent == "codex" and args.provider not in PROVIDER_BASE_URLS:
        print(f"unsupported Codex provider: {args.provider}", file=sys.stderr)
        return 2

    if args.agent == "codex" and args.max_agent_cost_usd is not None:
        parser.error(
            "--max-agent-cost-usd is a Claude-only limit; use the recorded Codex wall limit"
        )
    if args.reasoning_effort is not None and args.agent not in {"codex", "sanka-native"}:
        parser.error("--reasoning-effort requires Codex or Sanka native")
    for name in ("max_output_tokens", "max_context_bytes"):
        value = getattr(args, name)
        if value is not None and (args.agent != "sanka-native" or value <= 0):
            parser.error(
                f"--{name.replace('_', '-')} requires native harness and a positive integer"
            )
    if args.agent != "sanka-native" and args.sanka_workflow == "native-lifecycle-v1":
        parser.error("native-lifecycle-v1 requires the native harness")
    if args.agent == "sanka-native":
        if args.provider not in native_agent.ROUTES:
            parser.error("native harness supports direct OpenAI and Fireworks API routes")
        if args.agent_bin is not None:
            parser.error("native harness does not use --agent-bin")
        if args.out.exists() and any(args.out.iterdir()):
            parser.error("native output already exists; preserve the previous attempt")
        args.reasoning_effort = args.reasoning_effort or "high"
        args.route_kind = "openai-responses" if args.provider == "openai" else "openai-chat"
        args.billing_mode = "subscription" if subscription_run else "api_key"
        if subscription_run:
            args.route_kind = "codex-managed-subscription"
            if any(
                value is not None
                for value in (
                    args.price_in,
                    args.price_out,
                    args.price_cached,
                    args.max_agent_cost_usd,
                )
            ):
                parser.error("subscription runs must not use API prices or dollar caps")
        if args.gateway_profile:
            parser.error("native harness uses direct API keys, not gateway profiles")
        if not subscription_run and not os.environ.get(native_agent.ROUTES[args.provider][1]):
            parser.error("native harness requires the selected provider API key")
        prices = (args.price_in, args.price_out)
        if any(p is not None for p in prices) and not all(
            p is not None and math.isfinite(p) and p >= 0 for p in prices
        ):
            parser.error("supply both finite nonnegative --price-in and --price-out")
        if args.price_cached is not None and (
            not math.isfinite(args.price_cached)
            or args.price_in is None
            or not 0 <= args.price_cached <= args.price_in
        ):
            parser.error("--price-cached must be finite and between zero and --price-in")
        if args.max_agent_cost_usd is not None and args.price_in is None:
            parser.error("native cost cap requires explicit provider prices")
        if args.sanka_workflow not in {"availability-v1", "native-lifecycle-v1"}:
            parser.error("native harness owns the lifecycle; omit --sanka-workflow")

    try:
        validate_candidate_id(args.candidate_id)
    except ValueError as exc:
        parser.error(str(exc))

    task_dir = args.task.resolve()
    source = task_dir / "source"
    scenarios = task_dir / "public-tests" / "scenarios.json"
    if not source.is_dir() or not scenarios.is_file():
        print(f"not a benchmark task: {task_dir}", file=sys.stderr)
        return 2
    mode = _candidate_mode(args.candidate_id)
    if mode is None:
        print(
            "candidate id must end in -alone, -sanka-cli, -with-sanka, or "
            "-with-sanka-readiness-aware "
            "(optionally followed by a -s<k> sample suffix)",
            file=sys.stderr,
        )
        return 2
    if args.agent == "sanka-native" and mode == "readiness-aware":
        parser.error("native harness supports the three primary arms only")
    if mode != "alone" and args.sanka_bin is None:
        print(f"{args.candidate_id} requires --sanka-bin", file=sys.stderr)
        return 2
    if not 0 <= args.sanka_readiness_threshold <= 1:
        print("--sanka-readiness-threshold must be between 0 and 1", file=sys.stderr)
        return 2
    if args.wall_clock_seconds <= 0 or args.max_turns <= 0:
        print("turn and wall-clock budgets must be positive", file=sys.stderr)
        return 2
    if args.max_agent_cost_usd is not None and (
        args.agent not in {"claude-code", "sanka-native"}
        or not math.isfinite(args.max_agent_cost_usd)
        or args.max_agent_cost_usd <= 0
    ):
        print(
            "--max-agent-cost-usd requires Claude Code or native and a finite positive value",
            file=sys.stderr,
        )
        return 2
    if args.agent_bin is None:
        args.agent_bin = (
            sys.executable
            if args.agent == "sanka-native"
            else "claude"
            if args.agent == "claude-code"
            else "codex"
        )
    args.agent_bin = str(Path(shutil.which(args.agent_bin) or args.agent_bin).resolve())
    task = load_and_validate(task_dir / "task.yaml", "task")
    required_python = str(task["source"]["python"])
    actual_python = f"{sys.version_info.major}.{sys.version_info.minor}"
    if required_python != actual_python:
        print(
            f"task requires Python {required_python}; agent runtime is {actual_python}",
            file=sys.stderr,
        )
        return 2

    agent_version = subprocess.run(
        [args.agent_bin, "--version"],
        capture_output=True,
        text=True,
        check=False,
        env=isolated_environment(os.environ),
    ).stdout.strip()
    if args.agent == "sanka-native":
        agent_version = native_agent.version()

    lane_started = time.monotonic()
    sandbox_context = (
        tempfile.TemporaryDirectory(prefix="sanka-agent-")
        if args.sandbox is None
        else nullcontext(str(args.sandbox.resolve()))
    )
    with sandbox_context as temp:
        sandbox = Path(temp)
        sandbox.mkdir(parents=True, exist_ok=True)
        workspace = sandbox / "workspace"
        if workspace.exists():
            if any(workspace.iterdir()):
                print(f"sandbox workspace is not empty: {workspace}", file=sys.stderr)
                return 2
            workspace.rmdir()
        shutil.copytree(source, workspace)
        public_tests = workspace / "public-tests"
        public_tests.mkdir()
        shutil.copy2(scenarios, public_tests / "scenarios.json")
        claude_config = sandbox / "claude-config"
        raw_dir = sandbox / "raw"
        temp_dir = sandbox / "tmp"
        claude_config.mkdir()
        raw_dir.mkdir()
        temp_dir.mkdir()

        env = isolated_environment(
            os.environ,
            {
                "ANTHROPIC_API_KEY",
                "ANTHROPIC_AUTH_TOKEN",
                "ANTHROPIC_BASE_URL",
                "DEEPINFRA_API_KEY",
                "FIREWORKS_API_KEY",
                "OPENAI_API_KEY",
                "SANKA_HOME",
                "TOGETHER_API_KEY",
            },
        )
        native_key = None
        if args.agent == "sanka-native":
            native_key = "" if subscription_run else env[native_agent.ROUTES[args.provider][1]]
            for name in (
                *PROVIDER_ENV_KEYS.values(),
                "ANTHROPIC_API_KEY",
                "ANTHROPIC_AUTH_TOKEN",
                "ANTHROPIC_BASE_URL",
            ):
                env.pop(name, None)
        for name in (
            "DJANGO_SETTINGS_MODULE",
            "BENCH_DB_PATH",
            "CLAUDECODE",
            "CLAUDE_CODE_ENTRYPOINT",
        ):
            env.pop(name, None)
        env["CLAUDE_CONFIG_DIR"] = str(claude_config)
        env["CLAUDE_CODE_TMPDIR"] = str(temp_dir)
        env["TMPDIR"] = str(temp_dir)
        env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        if mode == "alone":
            env.pop("SANKA_HOME", None)
        else:
            env.setdefault("SANKA_HOME", str(sandbox / "sanka-home"))
            Path(env["SANKA_HOME"]).mkdir(parents=True, exist_ok=True)
        if args.agent == "claude-code":
            stripped = [
                "DEEPINFRA_API_KEY",
                "FIREWORKS_API_KEY",
                "OPENAI_API_KEY",
                "TOGETHER_API_KEY",
            ]
            if args.route_kind == "anthropic-native":
                stripped.extend(["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"])
            for name in stripped:
                env.pop(name, None)
        if mode != "alone":
            env = _sanka_runtime_env(env)
        readiness_context: dict[str, object] | None = None
        skill_record: dict[str, str] | None = None
        sanka_versions: str | None = None
        generated_files: dict[str, str] = {}
        prompt = task_prompt(task_dir, args.max_turns, args.wall_clock_seconds)
        if mode in {"sanka-cli", "with-sanka"}:
            assert args.sanka_bin is not None
            sanka_bin = args.sanka_bin.resolve()
            try:
                if mode == "with-sanka":
                    skill_record = install_sanka_skill(
                        sanka_bin, workspace, env, args.sanka_skill_sha256
                    )
                if args.sanka_workflow in {"artifacts-first-v1", "artifacts-first-v2"}:
                    readiness_context = _prepare_readiness_context(
                        workspace,
                        sanka_bin,
                        env,
                        args.sanka_readiness_threshold,
                        task["target"]["framework"],
                        args.sanka_workflow == "artifacts-first-v2",
                    )
                    if readiness_context["decision"] == "emit-scaffold":
                        generated_files = _promote_scaffold(workspace)
                        readiness_context["installed_files"] = generated_files
                else:
                    _enable_sanka_extension(
                        sanka_bin,
                        workspace=workspace,
                        env=env,
                        framework=task["target"]["framework"],
                    )
            except (OSError, RuntimeError, ValueError) as exc:
                print(f"{mode} setup failed: {exc}", file=sys.stderr)
                return 1
            sanka_versions = _sanka_tool_versions(sanka_bin, workspace=workspace, env=env)
            if readiness_context is not None:
                prompt += _readiness_prompt(readiness_context, sanka_bin)
            else:
                prompt += PROMPT_SANKA.format(sanka=sanka_bin)
            if mode == "with-sanka":
                assert skill_record is not None
                prompt += (
                    _inline_skill(skill_record)
                    if args.sanka_workflow == "artifacts-first-v2" or args.agent == "sanka-native"
                    else PROMPT_SANKA_SKILL
                )
        elif mode == "readiness-aware":
            assert args.sanka_bin is not None
            try:
                readiness_context = _prepare_readiness_context(
                    workspace,
                    args.sanka_bin.resolve(),
                    env,
                    args.sanka_readiness_threshold,
                    task["target"]["framework"],
                )
            except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
                print(f"readiness-aware Sanka preflight failed: {exc}", file=sys.stderr)
                return 1
            sanka_versions = _sanka_tool_versions(
                args.sanka_bin.resolve(), workspace=workspace, env=env
            )
            prompt += _readiness_prompt(readiness_context, args.sanka_bin.resolve())
        if args.agent == "sanka-native":
            command = []  # The controller stays outside every tool sandbox.
        elif args.agent == "codex":
            codex_home = sandbox / "codex-home"
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
                # Keep every event, including notifications after the terminal result.
                # agent-log.jsonl preserves the complete stream.
                "--output-format",
                "stream-json",
                "--verbose",
                *agent_isolation.claude_arguments(with_skill=mode == "with-sanka"),
            ]
        if args.max_agent_cost_usd is not None and args.agent != "sanka-native":
            command.extend(["--max-budget-usd", str(args.max_agent_cost_usd)])
        readable = [Path(args.agent_bin), Path(sys.prefix), Path(sys.base_prefix)]
        writable = [workspace, claude_config, temp_dir]
        if args.agent == "codex":
            writable.append(codex_home)
        if mode != "alone":
            sanka_python = args.sanka_bin.resolve().parent / "python"
            readable.extend(
                [args.sanka_bin.resolve().parent.parent, sanka_python.resolve().parent.parent]
            )
            if env.get("SANKA_HOME"):
                writable.append(Path(env["SANKA_HOME"]))
        terminal_reason: str | None = None
        timed_out = False
        agent_started_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        before_agent = _workspace_files(workspace)
        started = time.monotonic()
        first_target_seconds: float | None = 0.0 if "target_app.py" in before_agent else None

        def observe_target() -> None:
            nonlocal first_target_seconds
            if first_target_seconds is None and (workspace / "target_app.py").is_file():
                first_target_seconds = round(time.monotonic() - started, 3)

        try:
            native_stats = None
            if args.agent == "sanka-native":
                artifacts = args.out.resolve() / "native"
                (artifacts / "tools").mkdir(parents=True)
                readable.append(artifacts / "tools")
                tool_env = isolated_environment(
                    env, {"SANKA_HOME", "PYTHONPATH", "PYTHONDONTWRITEBYTECODE"}
                )
                tool_env["HOME"] = str(claude_config)
                tool_env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.defpath

                def execute_native(
                    argv: list[str], *, timeout: float
                ) -> subprocess.CompletedProcess[str]:
                    return agent_isolation.run(
                        argv,
                        workspace=workspace,
                        readable=readable,
                        writable=writable,
                        env=tool_env,
                        timeout=timeout,
                        observe=observe_target,
                    )

                runner = native_agent.Runner(
                    provider=args.provider,
                    model=args.model,
                    expected_model=args.actual_model_id or args.model,
                    effort=args.reasoning_effort,
                    key=native_key,
                    prompt=prompt,
                    workspace=workspace,
                    artifacts=artifacts,
                    execute=execute_native,
                    promote=lambda: _promote_scaffold(
                        workspace,
                        workspace
                        / (
                            ".sanka/output/flask"
                            if task["target"]["framework"] == "flask"
                            else ".sanka/agent-candidate/overlay"
                        ),
                    ),
                    sanka=args.sanka_bin.resolve() if mode != "alone" else None,
                    target=task["target"]["framework"],
                    max_turns=args.max_turns,
                    wall_seconds=args.wall_clock_seconds,
                    price_in=args.price_in,
                    price_out=args.price_out,
                    price_cached=args.price_cached,
                    max_cost=args.max_agent_cost_usd,
                    max_output_tokens=args.max_output_tokens or native_agent.MAX_OUTPUT_TOKENS,
                    max_context_bytes=args.max_context_bytes or native_agent.MAX_CONTEXT_BYTES,
                )
                if subscription_run:
                    from sanka_bench.subscription import Subscription

                    with Subscription(
                        runner.deadline,
                        str(args.subscription_bin) if args.subscription_bin else None,
                    ) as managed:
                        runner.exchange = managed
                        outcome, native_stats = runner.run()
                        native_stats["cost_basis"] = "subscription-no-marginal-cost"
                else:
                    outcome, native_stats = runner.run()
                generated_files = runner.generated
            else:
                outcome = agent_isolation.run(
                    command,
                    workspace=workspace,
                    readable=readable,
                    writable=writable,
                    env=env,
                    timeout=args.wall_clock_seconds,
                    observe=observe_target,
                )
        except (OSError, RuntimeError) as exc:
            print(f"agent isolation failed: {exc}", file=sys.stderr)
            return 1
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
                f"wall-clock timeout ({args.wall_clock_seconds}s) exhausted; the agent process was "
                "killed and the workspace was frozen as-is"
            )
        measured_ms = (time.monotonic() - started) * 1000
        agent_ended_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        codex_evidence = None
        codex_evidence_error = None
        if args.agent == "sanka-native":
            assert native_stats is not None
            stats = native_stats
        elif args.agent == "codex":
            if args.reasoning_effort is not None:
                try:
                    codex_evidence = _codex_session_evidence(
                        codex_home, args.model, args.reasoning_effort
                    )
                except (OSError, ValueError) as exc:
                    codex_evidence_error = str(exc)
            usage_event = (
                json.dumps({"usage": codex_evidence["total_token_usage"]}) if codex_evidence else ""
            )
            stats = _codex_stats(outcome.stdout + "\n" + usage_event, args, measured_ms)
        else:
            stats = claude_stats(
                outcome.stdout,
                billing_mode=args.billing_mode,
                requested_model_id=args.model,
                actual_model_id=args.actual_model_id or args.model,
                measured_ms=measured_ms,
            )
        out_dir = args.out.resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        if codex_evidence is not None:
            session = Path(str(codex_evidence.pop("session_path")))
            shutil.copyfile(session, out_dir / "codex-session.jsonl")
        raw = outcome.stdout.strip().splitlines()
        result = _claude_result(outcome.stdout) if args.agent == "claude-code" else None
        result_text = json.dumps(result) if result is not None else (raw[-1] if raw else None)
        for directory in (out_dir, raw_dir):
            if result_text is not None:
                (directory / "agent-result.json").write_text(result_text + "\n", encoding="utf-8")
            if outcome.stdout:
                (directory / "agent-log.jsonl").write_text(outcome.stdout, encoding="utf-8")
            if outcome.stderr:
                (directory / "agent-stderr.log").write_text(outcome.stderr, encoding="utf-8")
        if skill_record is not None:
            (out_dir / "sanka-skill.json").write_text(
                json.dumps(skill_record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
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
        after_agent = _workspace_files(workspace)
        changed_by_agent = {
            key
            for key in before_agent.keys() | after_agent.keys()
            if before_agent.get(key) != after_agent.get(key)
        }
        if args.agent == "sanka-native":
            changed_by_agent -= {
                key for key, digest in generated_files.items() if after_agent.get(key) == digest
            }
        telemetry: dict[str, object] = {
            "schema": "sanka-bench/agent-cell-telemetry/v1",
            "input_digest": os.environ.get("SANKA_BENCH_INPUT_DIGEST") or None,
            "harness": args.agent,
            "requested_model_id": args.model,
            "actual_model_id": args.actual_model_id or args.model,
            "provider": args.provider,
            "provider_variant": args.provider_variant,
            "route_kind": args.route_kind,
            "billing_mode": args.billing_mode,
            "gateway_profile": args.gateway_profile,
            "reasoning_effort": args.reasoning_effort,
            "codex_session": codex_evidence,
            "started_at": agent_started_at,
            "ended_at": agent_ended_at,
            "work": {
                **(
                    stats["work"]
                    if args.agent == "sanka-native"
                    else _observed_work(outcome.stdout)
                ),
                **(
                    {key: codex_evidence[key] for key in ("observed_model_responses", "tool_calls")}
                    if codex_evidence
                    else {}
                ),
            },
            "treatment": {
                "sanka_workflow": "native-lifecycle-v1"
                if args.agent == "sanka-native" and mode != "alone"
                else "readiness-aware"
                if mode == "readiness-aware"
                else args.sanka_workflow
                if mode != "alone"
                else None,
                "readiness_threshold": args.sanka_readiness_threshold if mode != "alone" else None,
                "generated_files": generated_files,
                "generated_files_retained_unchanged": sum(
                    after_agent.get(key) == digest for key, digest in generated_files.items()
                ),
                "agent_changed_files": len(changed_by_agent),
                "target_present_before_agent": "target_app.py" in before_agent,
            },
            "timing": {
                "lane_setup_seconds": round(started - lane_started, 6),
                "agent_wall_seconds": round(measured_ms / 1000, 6),
                "first_target_file_seconds": first_target_seconds,
            },
            "usage": {
                key: stats.get(key)
                for key in (
                    "input_tokens",
                    "cache_creation_input_tokens",
                    "cache_read_input_tokens",
                    "output_tokens",
                    "total_tokens",
                    "model_usage",
                    "reasoning_output_tokens",
                )
            },
            "cost": {
                "agent_estimate_limit_usd": args.max_agent_cost_usd,
                "cost_usd": stats.get("cost_usd"),
                "reported_equivalent_cost_usd": stats.get("reported_equivalent_cost_usd"),
                "basis": stats.get("cost_basis"),
            },
            "toolchain": {
                "agent_version": agent_version or None,
                "sanka_versions": sanka_versions,
                "sanka_skill": skill_record,
            },
            "digests": {
                "transcript_sha256": _sha256_bytes(outcome.stdout.encode()),
                "overlay_sha256": None,
            },
        }
        _write_json_atomic(out_dir / "telemetry.json", telemetry)
        if args.agent == "codex":
            # Runtime caches are disposable; keep sessions and all frozen evidence.
            for name in (".tmp", "shell_snapshots"):
                cache = codex_home / name
                if cache.exists():
                    shutil.rmtree(cache)
        if args.agent == "claude-code":
            events = []
            for line in raw:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict) and event.get("subtype") == "init":
                    events.append(event)
            expected_skills = {"sanka-cli"} if mode == "with-sanka" else set()
            inventories = [event.get("skills") for event in events]
            telemetry["isolation"] = {
                "backend": "seatbelt" if sys.platform == "darwin" else "bubblewrap",
                "skill_inventories": inventories,
                "tool_inventories": [event.get("tools") for event in events],
                "readable": [str(path) for path in readable],
                "writable": [str(path) for path in writable],
            }
            _write_json_atomic(out_dir / "telemetry.json", telemetry)
            if stats and (
                not inventories
                or any(
                    not isinstance(skills, list)
                    or not all(isinstance(skill, str) for skill in skills)
                    or set(skills) != expected_skills
                    for skills in inventories
                )
            ):
                print("agent isolation failed: unexpected skill inventory", file=sys.stderr)
                return 1
        if codex_evidence_error is not None:
            print(f"agent reported an error: {codex_evidence_error}", file=sys.stderr)
            return 1
        if readiness_context is not None:
            (out_dir / "sanka-readiness.json").write_text(
                json.dumps(readiness_context, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        if timed_out and not _has_model_activity(outcome.stdout) and not changed_by_agent:
            print(
                "agent reported an error: wall-clock timeout with no model activity",
                file=sys.stderr,
            )
            return 1
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
            elif str(stats.get("subtype") or "") == "error_max_budget_usd":
                terminal_reason = (
                    f"agent estimated-cost budget ({args.max_agent_cost_usd} USD) exhausted; "
                    "the workspace was frozen as-is"
                )
            else:
                print(f"agent reported an error: {stats.get('result') or stats}", file=sys.stderr)
                return 1
        if args.agent == "sanka-native":
            terminal_reason = "native harness stopped: " + str(stats["result"])
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

        overlay = out_dir / "overlay"
        if overlay.exists():
            shutil.rmtree(overlay)
        overlay.mkdir()
        for key in added:
            destination = overlay / key
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(workspace / key, destination)

        telemetry["digests"] = {
            "transcript_sha256": _sha256_bytes(outcome.stdout.encode()),
            "overlay_sha256": digest_tree(overlay),
        }
        _write_json_atomic(out_dir / "telemetry.json", telemetry)

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
            sanka_versions=sanka_versions,
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
    # Codex CLI 0.150 turns on its server-executed web-search tool by default.
    # OpenAI-compatible providers (Fireworks) reject requests that mix that tool
    # with client-executed function tools, and the migration task needs no web
    # access anyway, so every Codex cell runs with web search disabled — one
    # tool surface across providers, disclosed in GENERATED.md.
    command += [
        "--config",
        'web_search="disabled"',
        "--config",
        "project_doc_max_bytes=0",
        "--config",
        "features.shell_snapshot=false",
    ]
    effort = getattr(args, "reasoning_effort", None)
    if effort is not None:
        command += ["--config", f'model_reasoning_effort="{effort}"']
    command.append(prompt)
    return command


def _codex_stats(stdout: str, args: argparse.Namespace, measured_ms: float) -> dict[str, object]:
    turns = 0
    input_tokens = 0
    cached_input_tokens = 0
    cache_write_input_tokens = 0
    reasoning_output_tokens = 0
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
            cache_write_input_tokens = max(
                cache_write_input_tokens, int(usage.get("cache_write_input_tokens") or 0)
            )
            reasoning_output_tokens = max(
                reasoning_output_tokens, int(usage.get("reasoning_output_tokens") or 0)
            )
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
        "input_tokens": max(0, input_tokens - cached_input_tokens - cache_write_input_tokens),
        "cached_input_tokens": cached_input_tokens,
        "cache_creation_input_tokens": cache_write_input_tokens,
        "cache_read_input_tokens": cached_input_tokens,
        "reasoning_output_tokens": reasoning_output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "output_tokens": output_tokens or None,
        "recovered_error_events": error_events if terminal_kind == "turn.completed" else 0,
        "terminal_event": terminal_kind,
    }
    return stats


def _codex_session_evidence(home: Path, model: str, effort: str) -> dict[str, object]:
    """Keep native session evidence for effort, per-request billing and tool counts."""
    sessions = list((home / "sessions").rglob("*.jsonl"))
    if len(sessions) != 1:
        raise ValueError("Codex reasoning evidence requires exactly one session")
    raw = sessions[0].read_bytes()
    contexts = []
    requests = []
    calls = set()
    totals: dict[str, object] = {}
    seen = set()
    for line in raw.decode().splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        payload = event.get("payload", {})
        if event.get("type") == "turn_context":
            contexts.append({"model": payload.get("model"), "effort": payload.get("effort")})
        if event.get("type") == "response_item" and payload.get("type") in {
            "function_call",
            "custom_tool_call",
        }:
            calls.add(payload.get("call_id"))
        if event.get("type") == "event_msg" and payload.get("type") == "token_count":
            info = payload.get("info") or {}
            total = info.get("total_token_usage")
            last = info.get("last_token_usage")
            if isinstance(total, dict) and isinstance(last, dict):
                key = json.dumps(total, sort_keys=True)
                if key not in seen:
                    seen.add(key)
                    requests.append(last)
                    totals = total
    if not contexts or any(c != {"model": model, "effort": effort} for c in contexts):
        raise ValueError("Codex model or reasoning effort differs from the pinned request")
    return {
        "contexts": contexts,
        "request_usage": requests,
        "total_token_usage": totals,
        "observed_model_responses": len(requests),
        "tool_calls": len(calls),
        "session_path": str(sessions[0]),
        "sha256": _sha256_bytes(raw),
    }


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


def _has_model_activity(stdout: str) -> bool:
    activity_types = {
        "assistant",
        "user",
        "result",
        "tool",
        "tool_use",
        "tool_result",
        "item.started",
        "item.completed",
        "turn.completed",
        "turn.failed",
    }
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("type") in activity_types:
            return True
    return False


def _agent_error_is_terminal(stats: dict[str, object], *, timed_out: bool) -> bool:
    if not stats.get("is_error"):
        return False
    # A killed Codex process necessarily lacks a terminal JSONL event. Timeout
    # is already disclosed as the binding budget; freeze any non-empty work so
    # it can be graded instead of misclassifying budget exhaustion as provider
    # infrastructure. A real turn.failed remains terminal even at the deadline.
    return not (timed_out and stats.get("subtype") == "codex-no-terminal-event")


def _integer_token(item: dict[str, object], name: str) -> int | None:
    value = item.get(name)
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else None


def claude_stats(
    stdout: str,
    *,
    billing_mode: str,
    requested_model_id: str,
    actual_model_id: str,
    measured_ms: float,
) -> dict[str, object]:
    payload = _claude_result(stdout)
    if payload is None:
        return {}

    raw_usage = payload.get("modelUsage")
    model_usage: dict[str, dict[str, object]] = {}
    if isinstance(raw_usage, dict):
        for client_model, item in raw_usage.items():
            if not isinstance(item, dict):
                continue

            model_usage[str(client_model)] = {
                "client_model_id": str(client_model),
                "input_tokens": _integer_token(item, "inputTokens"),
                "cache_creation_input_tokens": _integer_token(item, "cacheCreationInputTokens"),
                "cache_read_input_tokens": _integer_token(item, "cacheReadInputTokens"),
                "output_tokens": _integer_token(item, "outputTokens"),
            }
    token_fields = (
        "input_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
        "output_tokens",
    )
    totals = {
        field: (
            sum(int(item[field]) for item in model_usage.values())
            if model_usage and all(item[field] is not None for item in model_usage.values())
            else None
        )
        for field in token_fields
    }
    total_tokens = (
        sum(int(value) for value in totals.values())
        if all(value is not None for value in totals.values())
        else None
    )
    raw_cost = payload.get("total_cost_usd")
    reported_cost = float(raw_cost) if isinstance(raw_cost, int | float) else None
    subscription = billing_mode == "subscription"
    raw_duration = payload.get("duration_ms")
    duration_ms = (
        float(raw_duration) if isinstance(raw_duration, int | float) else float(measured_ms)
    )
    return {
        "num_turns": payload.get("num_turns"),
        "duration_ms": duration_ms,
        "total_cost_usd": reported_cost,
        "cost_usd": None,
        "reported_equivalent_cost_usd": reported_cost,
        "cost_basis": (
            "subscription-no-marginal-cost"
            if subscription
            else "claude-code-reported-equivalent-unverified"
        ),
        "requested_model_id": requested_model_id,
        "actual_model_id": actual_model_id,
        "billing_mode": billing_mode,
        **totals,
        "total_tokens": total_tokens,
        "model_usage": model_usage,
        "is_error": payload.get("is_error"),
        "subtype": payload.get("subtype"),
        "result": payload.get("result"),
        "terminal_event": payload.get("type"),
    }


def _claude_result(stdout: str) -> dict[str, object] | None:
    """Find the terminal summary even when background notifications follow it."""
    for line in reversed(stdout.splitlines()):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(payload, dict)
            and payload.get("type") in (None, "result")
            and "num_turns" in payload
        ):
            return payload
    return None


def _agent_stats(stdout: str) -> dict[str, object]:
    payload = _claude_result(stdout)
    if payload is None:
        return {}
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
        "  command: scripts/run_agent_candidate.py (prompt and budget in GENERATED.md)",
    ]
    duration = stats.get("duration_ms")
    cost = stats.get("cost_usd") if "cost_usd" in stats else stats.get("total_cost_usd")
    equivalent_cost = stats.get("reported_equivalent_cost_usd")
    turns = stats.get("num_turns")
    lines.extend(
        [
            "stats:",
            f"  requested_model_id: {json.dumps(args.model)}",
            f"  actual_model_id: {json.dumps(args.actual_model_id or args.model)}",
            f"  billing_mode: {json.dumps(args.billing_mode)}",
            f"  cost_basis: {json.dumps(str(stats.get('cost_basis') or 'agent-reported'))}",
        ]
    )
    if isinstance(turns, int | float):
        lines.append(f"  turns: {int(turns)}")
    if isinstance(duration, int | float):
        lines.append(f"  duration_seconds: {round(duration / 1000, 3)}")
    for field in (
        "input_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
        "output_tokens",
        "total_tokens",
    ):
        value = stats.get(field)
        if isinstance(value, int | float):
            lines.append(f"  {field}: {int(value)}")
    lines.append(
        f"  cost_usd: {round(float(cost), 6) if isinstance(cost, int | float) else 'null'}"
    )
    lines.append(
        "  reported_equivalent_cost_usd: "
        + (
            str(round(float(equivalent_cost), 6))
            if isinstance(equivalent_cost, int | float)
            else "null"
        )
    )
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
    sanka_versions: str | None = None,
) -> None:
    duration = stats.get("duration_ms")
    minutes = f"{int(duration) / 60000:.1f} min" if isinstance(duration, int | float) else "unknown"
    cost = stats.get("cost_usd") if "cost_usd" in stats else stats.get("total_cost_usd")
    cost_text = f"${float(cost):.2f}" if isinstance(cost, int | float) else "unknown"
    equivalent = stats.get("reported_equivalent_cost_usd")
    equivalent_text = (
        f"${float(equivalent):.2f}" if isinstance(equivalent, int | float) else "not applicable"
    )
    if args.agent in {"claude-code", "sanka-native"}:
        budget_text = str(args.max_turns)
    else:
        budget_text = (
            f"{args.max_turns} requested - not enforced by Codex CLI; "
            f"the {args.wall_clock_seconds}s wall-clock timeout is the binding limit"
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
    agent_label = {
        "claude-code": "Claude Code",
        "codex": "Codex CLI",
        "sanka-native": "Sanka native",
    }[args.agent]
    provider = args.provider
    web_search_text = (
        "Claude Code default tool set"
        if args.agent == "claude-code"
        else "disabled; no web-search tool"
    )
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
| Web search | {web_search_text} |
| Reasoning effort | {getattr(args, "reasoning_effort", None) or "provider default (not pinned)"} |
| Recovered transport notices | {stats.get("recovered_error_events", 0)} |
| Cost basis | {stats.get("cost_basis", "agent-reported")} |
| Requested model | `{args.model}` |
| Actual model | `{args.actual_model_id or args.model}` |
| Route / billing | {args.route_kind} / {args.billing_mode} |
| Gateway profile | {args.gateway_profile or "not applicable"} |
| Turn budget | {budget_text} |
| Turns used | {stats.get("num_turns", "unknown")} |
| Duration | {minutes} |
| Actual cost | {cost_text} |
| Claude Code API-equivalent estimate | {equivalent_text} |
| Terminal | {terminal_reason or "completed within budget"} |
| Attempt | {attempt_text} |
| Sanka CLI | {sanka_versions or "not offered"} |
| Sanka readiness preflight | {readiness_value} |

Files added by the agent: {len(added)}. Contract-violating modifications to
existing source files (dropped from the overlay, since candidates are
add-only):
{modified_text}
{readiness_section}

## Prompt (verbatim)

````
{prompt}
````
""",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
