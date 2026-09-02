# Coding-agent baseline provenance: claude-code-with-sanka

Produced unattended by `scripts/run_agent_candidate.py` — no human
intervention between prompt and frozen overlay.

| Disclosure | Value |
|---|---|
| Agent | Claude Code (`2.1.241 (Claude Code)`) |
| Model | `claude-sonnet-5` |
| Turn budget | 60 |
| Turns used | 40 |
| Duration | 6.8 min |
| Reported cost | $1.13 |
| Attempt | 2 (previous attempt failed on infrastructure, not agent quality: API connection lost mid-response after 41 turns) |

Files added by the agent: 2. Contract-violating modifications to
existing source files (dropped from the overlay, since candidates are
add-only):
none — the add-only contract was respected

## Prompt (verbatim)

```
Migrate this Django REST Framework application to FastAPI, natively.

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
5. The database path comes from the BENCH_DB_PATH environment variable through
   the existing settings module; reuse that mechanism unchanged.

A Python interpreter with django, djangorestframework, and fastapi installed
is available at: <repo>/.venv/bin/python3
Use it to run the original app and your app side by side (django test client
vs fastapi TestClient) and verify every scenario before you finish. Do not
consider the task done until every scenario matches exactly.

The Sanka migration CLI is installed at: <local-path>
It can generate a native FastAPI candidate for you:

    <local-path> scan .
    <local-path> plan --to fastapi
    <local-path> apply --root . --bench-candidate ./bench-candidate

The bench-candidate overlay contains target_app.py and its supporting files;
copy them to the repository root as your deliverable, verify the scenarios,
and adjust them if needed.

```
