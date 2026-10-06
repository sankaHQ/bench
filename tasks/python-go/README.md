# Python to Go — implemented, not run

Status: **unqualified; execution disabled** (2026-10-05).

Four task v0.3 manifests, the Go evaluator, harness wiring and controls are
implemented. They have not been compiled or executed. Historical FastAPI/Flask
results remain a separate 17-task cohort. The new tasks are discoverable by static
validation; scored Go campaign admission requires explicit qualification evidence
and paid-run authorization. The template cannot launch a campaign as supplied.

| ID | Behavior | Reused source | Public / full scenarios |
| --- | --- | --- | --- |
| [python-go-001](python-go-001/task.yaml) | CRUD and validation | drf-fastapi-001 | 5 / 5 |
| [python-go-002](python-go-002/task.yaml) | Tokens and object permissions | drf-fastapi-002 | 13 / 13 |
| [python-go-003](python-go-003/task.yaml) | Nested writes and rollback | drf-fastapi-006 | 7 / 32 |
| [python-go-004](python-go-004/task.yaml) | Tenant wallets and idempotency | drf-flask-004 | 8 / 32 |

All 82 full scenarios and 33 public subsets preserve original bytes. Per-task
`task.draft.json` files retain the original source/task/scenario hashes and hold
status; they are provenance records, not runner authorization. Source fixtures are
Apache-2.0 synthetic applications. Reusing them measures a new destination, not
four independent new source applications. Evaluation scenarios are public in the
repository, even though omitted from candidate workspaces.

## Grading contract

The original Python application remains the oracle. Existing eight hard gates
apply: source qualification, regression/build checks, target boot, native target,
response parity, database parity, side-effect parity and determinism. Each full
scenario runs twice from fresh state; multi-request scenario chains share their
own database. Source and target never share mutable databases.

The public Go contract is a root `NewBenchApp(databasePath string) (*fiber.App,
error)` factory and a buildable `cmd/api/main.go`. Both arms receive identical
Go module locks: Go 1.26.5, Fiber v3.5.0 and modernc.org/sqlite v1.57.0. Standalone
servers use DATABASE_URL and PORT. Foreign keys must be enabled. No module
replacements, vendored framework, candidate assembly/object files or go:linkname
are allowed. CLI-generated `OpenSQLite`/`NewApp` receive a small benchmark adapter.

The evaluator builds all Go packages and cmd/api offline, then compiles its own
Fiber App.Test probe. **It measures app behavior through the test client; it does
not launch or verify the production TCP listener.** Python seeds and observes
SQLite outside the serving sandbox. Inside it, only the compiled probe, candidate
workspace and that scenario's database directory are mounted. No Python runtime,
external network or other executable is supplied. Child processes and outbound
connections are observed by an external strace; attempts fail native grading.

Native evidence comes from a dedicated syscall in the trusted probe after Fiber
App.Test and response serialization, with a response digest and independently
observed instruction address. Candidate stdout alone cannot attest dispatch.
This requires Linux/amd64 or Linux/arm64, non-PIE output and working user namespaces. It is a
benchmark harness, not a security boundary against arbitrary unsafe native-code
control-flow hijacking. Unsupported sandbox/tracing environments fail closed.

The independently authored reference and four negative controls (Python process
attempt, missing writes, early-exit stdout forgery, unchanged Python) are present
but **unqualified**. Their future 20-cell control matrix must pass before scored
runs. No unsupported scenario may be deleted to improve results.

## Execution hold

Sanka CLI 0.3.9 and Python-to-Go extension 0.1.0a17 are selected in the
[release lock](../../src/sanka_bench/python_go_release.json). Models, budgets,
host paths and evaluator image digest remain unselected.
Destination dependency locks are already frozen; changing them
requires changing the public contract and requalifying. Runtime wheel payloads
must match all six pinned release wheels. Marketplace installation uses an
immutable revision and the returned extension lock is checked before generation.

See the [implementation/run plan](../../docs/superpowers/plans/2026-10-05-python-go-bench.md)
and [campaign instructions](../../campaigns/python-go/README.md). Do not run the
historical suite or reuse its Model Only outcomes as Go results.

Static provenance check (reads JSON/hashes only):

```bash
PYTHONPATH=src python scripts/check_python_go_drafts.py
```
