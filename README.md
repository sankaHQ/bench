# Sanka Migration Bench

The default agent is now the [Sanka native harness](docs/native-harness.md):
direct provider APIs, controller-owned Sanka lifecycle, and the same independent
benchmark tasks and grading. Legacy Claude Code/Codex adapters remain explicit options.

## Provider login

> **Experimental — DWYOR (Do With Your Own Risk).** Sanka Bench's login
> integration is unofficial and is not endorsed by OpenAI or Anthropic. It
> delegates sign-in to their official CLIs; it does not provide a provider-approved
> subscription API for the native harness. Authentication behavior and provider
> terms may change. You are responsible for your account, usage limits, and
> compliance with the applicable provider terms. Subscription-backed benchmark
> generation uses an experimental managed transport. Independent GPT workers are
> serialized; live expiry/revocation recovery is not yet qualified.

Install the [Codex CLI](https://learn.chatgpt.com/docs/cli), then run:

```bash
sanka-bench login --provider chatgpt --device-auth
sanka-bench login status --provider chatgpt
sanka-bench logout --provider chatgpt

# Requires the official Claude Code CLI; opens its browser login flow.
sanka-bench login --provider claude
sanka-bench login status --provider claude
sanka-bench logout --provider claude
```

`sanka-bench login` also defaults to device authentication. Open the verification
URL printed by Codex, sign in with your ChatGPT subscription account, and enter
the one-time code. Device login must be enabled in your ChatGPT account or
workspace; see [OpenAI authentication](https://learn.chatgpt.com/docs/auth).
Ctrl-C cancels the pending login. Status and logout operate on Sanka Bench's
session, not your regular Codex login.

ChatGPT is the default provider. Codex manages its login and token refresh. Credentials stay in the private
`~/.sanka-bench/codex/` directory, outside repositories and benchmark artifacts.
Treat that directory like a password; do not commit or share it. Sanka Bench
does not inherit API keys or your existing `CODEX_HOME` for these commands.
Login, status, and logout take an exclusive process lock: a competing command
fails with `session is busy` instead of changing credentials concurrently.
The lock is released when the owning processes exit; do not delete its file.

The native harness supports ChatGPT subscriptions with `--provider openai
--billing-mode subscription`. It delegates inference and refresh to Codex App Server,
with built-in environments and ambient plugins disabled. Only the benchmark's
sandboxed tools can access task files. Each cell gets a fresh ephemeral conversation;
credentials remain outside cell artifacts. The coordinator pins the Codex binary.
API keys are stripped, and authentication failures do not fall back to API billing.

One subscription cell holds the account lock for its full lifetime. Run different
API providers alongside it; do not start independent concurrent GPT workers.
Codex adds its own instructions and manages context/output limits, so this transport
is reported separately from direct API runs. Tool count and wall-time limits remain
harness-enforced. Token usage includes Codex overhead; subscription dollar cost is
null rather than an invented API price. Native response/context byte settings do
not impose equivalent limits inside Codex's managed model loop.

For Claude, Bench launches the unmodified `claude auth login --claudeai` command
with a private `~/.sanka-bench/claude/` configuration directory. Claude Code owns
credential storage (including its macOS Keychain), browser authentication, and
refresh; Bench does not read or export its tokens. `--device-auth` is ChatGPT-only.
Inherited Anthropic API keys, bearer tokens, and OAuth overrides are removed.
Each provider has its own command lock, so logging out of one does not invoke the
other provider's CLI. These locks coordinate Bench commands, not independently
started vendor CLIs.

Claude login is for the official Claude Code application. It does not authorize
using subscription tokens in the Sanka-native HTTP adapter, and this new login
store is not yet wired to benchmark generation. See
[Anthropic authentication boundaries](https://code.claude.com/docs/en/legal-and-compliance).

Simultaneous subscription workers remain blocked. Cross-provider parallelism must
pass the normal isolation and boot qualification first. Login and tool-round-trip
tests do not prove recovery from a revoked or expired session; authentication errors
stop admission for investigation and any rerun retains its original attempt.

Sanka Migration Bench (repository `sankaHQ/bench`, package `sanka-bench`) is a tool-neutral, repository-level
benchmark for evaluating whether a software migration preserves behavior and
actually reaches its declared target architecture.

The first benchmark lane is intentionally narrow:

> Django REST Framework to FastAPI, retaining the Django ORM and database
> schema while replacing the request-serving layer.

The original application is the behavior oracle. Candidates are compared on
HTTP behavior, database mutations, and target-framework compliance rather than
source-code similarity to one preferred implementation.

## Status

Version 1 has eleven `drf-fastapi` tasks (170 verifiable method-routes).
The additional `drf-flask` lane has six migration tasks: three reuse existing DRF
source families; wallets, conditional documents and capacity reservations add three
independent applications. There are seventeen source/target tasks across fourteen
source applications; compare and report each lane separately.
Published numbers come only from runs whose frozen candidates, evaluator
reports, and full agent logs exist, measured as
[docs/measurement-design.md](docs/measurement-design.md) specifies; nothing is
estimated. Results are published at [sanka.com/bench](https://sanka.com/bench).

## Scoring

**Migration Quality Score = verified routes ÷ total routes in the lane's
suite, pass@1.** A route (here: an HTTP method-route) counts only when its
whole task passes every hard gate; a run that produces no bootable candidate
scores zero. Denominators are frozen per suite version and grow only by
adding tasks. Lanes are scored separately — framework, data, and object
lanes will never be blended into one number, because their route units are
not commensurable. Score changes bump the score version (current: v0.2).

The FastAPI lane has eleven synthetic source fixtures. `drf-fastapi-001` covers CRUD and validation;
`drf-fastapi-002` adds database-backed `TokenAuthentication`, `IsAuthenticated`,
and object-level permissions (author-or-read-only), with 401-variant,
403, and `WWW-Authenticate`/`Allow` header scenarios — a native candidate must
reimplement token authentication without loading DRF. `drf-fastapi-003` adds
writable nested serializers with DRF's index-keyed nested error format, a
transactional create whose business-rule failure must leave the database
unchanged (the rollback contract is proven by database parity), unique-field
messages, decimal digit/precision errors with string representation, and
choice-field errors. `drf-fastapi-004` is the first hard-tier fixture and the
first with a visible/hidden scenario split: its ledger behavior lives partly
in Django signals (`post_save`/`post_delete` keep an API-read-only
`Account.balance` and an append-only audit trail in step, connected in
`AppConfig.ready`), plus a custom transfer action that locks both accounts in
pk order and rolls back on insufficient funds, and cascade deletes whose
audit rows record Django's descending-pk `post_delete` order. Candidates see
5 public scenarios; the evaluator grades a 17-scenario superset (12 hidden)
covering balance read-only enforcement, `F()` composition, reverse postings,
rollback-by-database-parity, audit ordering, and Decimal string forms — a
probe candidate implementing only the visible surface passes all 5 public
scenarios and fails 10 of the 12 hidden ones.
`drf-fastapi-005` expands authentication into a hard-tier permission matrix:
expiring database tokens precede session authentication on one viewset,
unsafe session writes enforce CSRF, `get_permissions()` makes list public,
create authenticated, destroy staff-only, ordinary details owner-only, and a
custom review action staff-only. Candidates see 7 scenarios; the evaluator
grades a 31-scenario superset whose exact 401/403/404 bodies and
`WWW-Authenticate`/`Allow` headers pin authentication-before-permission,
no fallback from a bad token to a valid session, detail-only object checks,
and staff action overrides. A visible-only probe passes all 7 public
scenarios and fails 16 of the 24 hidden scenarios.
`drf-fastapi-006` deepens nested writes to three levels
(`Order -> OrderItem -> Adjustment`). Supplying `items` during PUT or PATCH
atomically replaces the entire child graph; omitting it during PATCH preserves
every existing child and adjustment byte-for-byte. Candidates see 7 scenarios
while the evaluator grades a 32-scenario superset (25 hidden) covering
string-indexed errors at both list depths, defaults and empty lists,
middle-level SKU and deepest-level adjustment uniqueness, failures after the
Nth child has already been written, and rollback of parent changes plus deleted
children. A visible-only probe passes all 7 public scenarios and fails 25 of
the 25 hidden scenarios.
`drf-fastapi-007` makes response representation itself part of the contract:
encoded cursor pagination and page walking compose with search and ordering,
ties use deterministic primary-key direction, Decimal fields remain fixed-scale
strings, aware datetimes render in `Asia/Tokyo`, and detail responses carry
content-derived ETags. Matching `If-None-Match` requests return an empty 304
with exact cache headers. Candidates see 6 scenarios while the evaluator grades
a 30-scenario superset (24 hidden) covering stable cursors after inserts,
three-page walks, query-preserving envelopes, malformed cursors, directional
ties, empty searches, decimal/timezone normalization, wildcard/list ETags, and
stale versus current validators after mutation. A visible-only probe passes all
6 public scenarios and fails 19 of the 24 hidden scenarios.
`drf-fastapi-008` migrates one `Entry` domain exposed simultaneously through
function views, classic `APIView` classes with a hand-rolled dispatch lifecycle,
and a router-backed `ModelViewSet`. Regex lookups accept dots, plus signs, and
at-signs; a formatted route table appended after the main URL list triggers
`SANKA_DRF_DYNAMIC_ROUTE`; and each view style has a distinct slash contract.
Candidates see 8 canonical scenarios while the evaluator grades a 32-scenario
superset (24 hidden) covering alternate slash redirects, a second non-slug code,
cross-style create/update/delete visibility, validation failures, and rejected
full-update rollback. A visible-only probe passes all 8 public scenarios and
fails 20 of the 24 hidden scenarios.
`drf-fastapi-009` makes file transport observable: a multipart collection
stores validated `FileField` bytes and deterministic metadata, binary download
routes preserve attachment disposition and byte parity, and explicit `.json`
and `.api` routes negotiate JSON versus a vendor media type. Candidates see 8
scenarios while the evaluator grades a 32-scenario superset (24 hidden)
covering unusual multipart boundaries, suffix-specific uploads and downloads,
case-insensitive extensions, the 32-byte boundary, exact validation errors,
missing objects, mutation chains, rejected-write database parity, and a
filesystem ledger of every stored byte. A visible-only probe passes all 8
public scenarios and fails 13 of the 24 hidden scenarios.
`drf-fastapi-010` makes a versioned order state machine observable. Draft,
submitted, approved, shipped, and cancelled orders follow an explicit legal
transition graph; PATCH and transition requests use optimistic locking; every
successful write increments the version exactly once and appends one audit
event. Candidates see 7 scenarios while the evaluator grades a 32-scenario
superset (25 hidden) that exhausts all 25 current-status/target-status pairs,
pins exact 400/409 bodies, and proves stale PATCH and transition requests leave
both orders and events unchanged. A visible-only probe passes all 7 public
scenarios and fails all 25 hidden scenarios.
`drf-fastapi-011` makes related-row aggregates and computed fields observable.
Its paginated account list combines filtered `Count`/`Sum` annotations,
deterministic computed ordering, fixed-scale Decimal strings, and method fields
derived from the latest prefetched transaction; transaction writes must
recompute both list and grouped-summary results. Candidates see 7 scenarios
while the evaluator grades a 32-scenario superset (25 hidden) covering both
pages, ordering ties, mutation chains, negative/zero/large totals, related-row
moves, empty accounts, empty groups, and a fully empty dataset. A visible-only
probe passes all 7 public scenarios and fails 17 of the 25 hidden scenarios.

Baselines live at `baselines/<task>/<candidate>/`. Every task carries four
controls:

| Baseline | Expected result |
| --- | --- |
| No-op (unchanged source) | Fails target boot and native-target compliance |
| Compatibility bridge | Preserves behavior by dispatching into the original application; fails the native-serving gate |
| Native human reference | Passes behavior, database, regression, and native FastAPI gates |
| Sanka native converter (`sanka apply --bench-candidate`) | Frozen output of the pinned engine release; passes only where the converter's envelope covers the task |

The converter baseline is regenerated whenever the pinned engine changes; its
`candidate.yaml` records the engine revision and command, and its gap report
names every route the engine left to a human. Coding-agent candidates are
produced by `scripts/run_agent_candidate.py` during measured runs and are never
committed as baselines: every published agent number traces to a frozen
candidate directory whose `GENERATED.md` discloses the prompt verbatim, turns,
wall time, and reported cost. The shared contract requires every evaluated
request to reach a workspace-owned FastAPI `APIRoute` (subclasses included);
raw Starlette routes, implicit framework redirects, mounts, and compatibility
dispatchers do not satisfy native-serving evidence in any arm.

Experiments may add a separately labelled
`*-with-sanka-readiness-aware` arm. Before the agent starts, the harness runs
`sanka scan` and `sanka plan`, freezes `sanka-readiness.json`, and emits a
scaffold only when native readiness reaches the configured threshold (50% by
default). Below it, the agent receives the readiness number and the verifier
command — no scaffold and no route checklist; the unsupported and unscanned
route inventory is frozen in `sanka-readiness.json` for the record only. This
diagnostic arm never replaces or rewrites the official alone/with-Sanka pass@1
result.

The native-target gate is decided by recorded serving evidence, not source
text. Every candidate scenario is served in a fresh guarded process that arms
an un-removable audit hook before any candidate code loads. The hook records
imports of DRF and Django request-serving machinery, process creation, and
socket connections; the guard also verifies the scenario was served by a
FastAPI `APIRoute` whose endpoint code lives inside the candidate workspace.
A facade that hides DRF dispatch behind an imported helper therefore fails
even though its entrypoint text looks clean (see
`tests/fixtures/obfuscated-bridge`). Textual pattern checks remain in results
as diagnostics only.

## Run locally

```bash
uv sync --frozen --extra fixture --group dev
uv run sanka-bench validate
uv run sanka-bench evaluate \
  --runner local \
  --task tasks/drf-fastapi/drf-fastapi-001 \
  --candidate baselines/drf-fastapi-001/native-reference
```

The default runner is Docker and disables network access while evaluating:

```bash
uv run sanka-bench evaluate \
  --task tasks/drf-fastapi/drf-fastapi-001 \
  --candidate baselines/drf-fastapi-001/native-reference
```

Evaluate every required baseline locally or in the isolated container:

```bash
make baselines
make docker-baselines
```

For complete development validation, run `make check`. It runs the full test
suite with two workers by default; use `make check TEST_WORKERS=1` when memory
is constrained. `make test-unit` provides quick harness feedback, and
`make test-evaluator-008` evaluates and asserts all four baselines for one task.
CI runs every task's evaluator tests once, plus all Docker baselines.

## Repository boundary

- This repository owns evaluator schemas, public fixtures, isolation, baseline
  runners, and reports.
- `sankaHQ/sanka` owns the Sanka runtime and the `sanka scan`, `plan`, `apply`,
  and `verify` product experience.
- Hidden Verified-set tests must remain outside candidate-visible public source.
- The evaluator must be able to grade Sanka and non-Sanka candidates through the
  same candidate contract.

## Roadmap

The suite is deliberately small and verification-heavy today; the plan is to
grow it the same way it started — every task ships with its behavior oracle,
public scenarios, and hard gates, never as a prompt list.

1. **Hard tier (~5 tasks).** These extend the first three introductory tasks,
   each targeting a
   failure mode already observed in recorded runs or real-app scans:
   auth-and-permission matrices (multiple authentication schemes, per-action
   and object-level permissions, 401/403 branch coverage; landed as
   `drf-fastapi-005`); signal-driven
   side-effects and transaction boundaries (`post_save` chains, `F()`
   updates, `select_for_update` — database-mutation parity does the work;
   landed as `drf-fastapi-004`, the first task with a hidden scenario
   split); deep writable-nested graphs with DRF's index-keyed error shapes
   (landed as `drf-fastapi-006`); exact response-shape parity (cursor
   pagination, ordering/search filters, Decimal string forms, timezone
   boundaries, conditional responses; landed as `drf-fastapi-007`); and a
   legacy mixed-style app (function views + `APIView` + ViewSets, regex and
   dynamic routes; landed as `drf-fastapi-008`). File transport and format
   negotiation landed as `drf-fastapi-009`, including multipart boundaries,
   exact stored/downloaded bytes, and explicit `.json`/`.api` routes. State
   transitions and optimistic concurrency landed as `drf-fastapi-010`, with an
   exhaustive legal/illegal matrix, exact version increments, audit events,
   and rejected-write rollback. Aggregate and computed-field behavior landed as
   `drf-fastapi-011`, including filtered counts/sums, computed ordering,
   pagination consistency, mutation recomputation, and empty-group semantics.
2. **Real-application tasks.** Oracle-ized slices of permissively licensed
   OSS Django apps (readthedocs and peering-manager are already pinned as
   corpus candidates in
   [sanka-examples](https://github.com/sankaHQ/sanka-examples)), lifting the
   suite from 68 endpoints toward hundreds.
3. **Scale.** On the order of fifty tasks across tiers, with the task list
   published the way mature benchmarks publish theirs.
4. **New lanes.** Data-systems migrations (e.g. `markdown-sqlite`,
   `pg-clickhouse`) and object migrations (e.g. `sfdc-hubspot`), each with
   its own route unit, gates, and per-lane score.

## Contributing

Task proposals are welcome once this repository is public: open an issue
describing the source application, the behaviors the oracle must capture,
and why existing tasks do not already cover the failure mode. A task lands
only with its scenarios, evaluation config, and at least the no-op and
human-reference baselines.

## License

Apache-2.0. Candidate outputs under `baselines/` retain the disclosures in
their `GENERATED.md`.

Produce a frozen coding-agent baseline for one task (unattended, one
attempt, full disclosure of model, tool version, prompt, budget, turns,
duration, and reported cost in the candidate's GENERATED.md):

```bash
uv run python scripts/run_agent_candidate.py \
  --task tasks/drf-fastapi/drf-fastapi-001 \
  --candidate-id claude-code-<model>-alone \
  --out baselines/drf-fastapi-001/claude-code-<model>-alone \
  --agent claude-code \
  --agent-bin <pinned-claude-binary> \
  --model <exact-requested-model-id> \
  --actual-model-id <verified-backend-model-id> \
  --provider anthropic \
  --provider-variant subscription-standard \
  --route-kind anthropic-native \
  --billing-mode subscription
```

Official model matrices use this same pinned Claude Code harness for every
model treatment. Claude subscriptions use the native authenticated route;
GPT and other models may use a declared Anthropic-protocol gateway only after
that exact route passes qualification. The compatibility Codex runner is not
an official matrix harness.

The three configurations share the same model, budget, and grading contract:
model only, model + Sanka CLI, and model + Sanka CLI + Skills. For new runs,
pin `execution.sanka_workflow` to `artifacts-first-v1` and
`execution.sanka_readiness_threshold` to `0.5`. Both Sanka arms run the same
scan/plan/apply preparation and receive its generated files before the agent
starts. Only the Skills arm installs the pinned project skill. Preparation time
is included in the comparison. Below the readiness threshold, both arms receive
the plan context and implement the native target without a scaffold.

The goal is accuracy at least equal to model-only, with fewer tokens, lower
inference cost, shorter execution time, and higher successful-task throughput.
These are measured requirements, never evaluator overrides. Reports flag paired
accuracy regressions and leave missing evidence or unverified cost unknown.
Run `python scripts/run_agent_matrix.py --manifest RUN/run-manifest.json report`
to rebuild the comparison; artifacts-first runs also generate it automatically.

Omitting the workflow retains the historical `availability-v1` treatment, where
the agent decides whether to use Sanka. Existing frozen results must not be
relabeled as artifacts-first. The `-with-sanka-readiness-aware` diagnostic remains
separate. Every frozen overlay is graded by the same tool-neutral evaluator.

For larger model matrices, use `scripts/run_agent_matrix.py` as the single
foreground coordinator. It preserves generated candidates across resumes,
drains their evaluations after a provider failure, records serving tiers with
`provider_variant`, validates telemetry and hashes, blocks aggregation if a
credential appears in an artifact, and never activates a declared backup
automatically. Execution budgets and concurrency are manifest-pinned, and the
report separates setup, agent, evaluation, end-to-end, and suite makespan. The
manifest, qualification, environment, cost, and recovery
contract is documented in
[docs/measurement-runs.md](docs/measurement-runs.md).

Render the collected reports into a static page and summary SVG — the hero
tally (tasks fully migrated per approach) and the per-task hard-gate matrix:

```bash
make baselines && make docker-baselines   # produce reports/*.json
make report                               # -> reports/index.html + reports/summary.svg
```

The render is deterministic for a given set of reports; the headline stays the
binary Fully Migrated count, never a blended score. Scenario-level HTTP,
database, and native-serving percentages appear underneath as
non-scoring diagnostics only; they cannot compensate for a failed hard gate.

See [docs/design.md](docs/design.md) for the implemented slice and next gates.

## License

Apache License 2.0. Third-party fixture repositories will retain their own
licenses and provenance records when added.

## Converter regression workflow

The manual **Converter regression** workflow runs the public
`sankaHQ/extensions` converter at an explicitly supplied full commit SHA against
its reviewed benchmark revision. It uses this private repository's read-only
GitHub token; no cross-repository secret or public fixture copy is needed.

```bash
gh workflow run converter-regression.yml --repo sankaHQ/bench --ref main \
  -f extensions_sha=<full-40-character-extensions-commit-sha>
```

Run it before releasing a changed converter and link the successful workflow and
private `converter-regression-<SHA>` artifact to the exact extensions head under
review. This is a manual regression/release check, not automatic coverage on
public extensions PRs. The runner and route expectations live in
[`extensions/scripts`](https://github.com/sankaHQ/extensions/tree/main/scripts);
the benchmark evaluator remains tool-neutral. See the
[converter check instructions](https://github.com/sankaHQ/extensions/blob/main/docs/converter-regression.md)
for local execution and the distinction between fully migrated, partial, and
expected-refusal outcomes.

## Flask lane and broader model comparison

The Flask lane uses native Flask URL dispatch evidence, endpoint provenance,
forbidden-import/process/network records, and the same independent HTTP,
database, side-effect and determinism gates as FastAPI. A Django WSGI bridge is
an explicit negative control, even when all responses match.

- `drf-flask-001`: optimistic locking, state transitions and atomic event records.
- `drf-flask-002`: multipart uploads, stored bytes, download headers and media types.
- `drf-flask-003`: decimal aggregates, stable pagination and computed fields.
- `drf-flask-004`: tenant-scoped wallet transfers, idempotency and atomic audit records.
- `drf-flask-005`: conditional document reads/writes, ETags and atomic revision history.
- `drf-flask-006`: timezone/DST validation, interval capacity and idempotent cancellations.

The first three reuse DRF sources from FastAPI tasks 010, 009 and 011 respectively, so they
measure destination diversity without pretending to be independent source apps.
Run `make test-evaluator-flask-001` (and 002/003/004/005/006) for qualified positive/negative
controls. `make check`, `make baselines`, `make docker-baselines` and CI include
the new lane, using bounded task shards.

The six Flask tasks contain 192 graded scenarios. Tasks 005 and 006 add 64 graded
scenarios and 24 public examples, authored after the artifacts-first-v2 treatment
and its fifteen-task paid run were frozen. They are reserved for a later comparison;
adding them does not change the current run's denominator.

See [the expanded comparison protocol](docs/expanded-comparison.md) before a paid
run. A 100% result on a single calibration task is not full-suite saturation.
