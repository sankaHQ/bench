# Sanka Migration Bench

Sanka Migration Bench (`sanka-bench`) is a tool-neutral, repository-level
benchmark for evaluating whether a software migration preserves behavior and
actually reaches its declared target architecture.

The first benchmark lane is intentionally narrow:

> Django REST Framework to FastAPI, retaining the Django ORM and database
> schema while replacing the request-serving layer.

The original application is the behavior oracle. Candidates are compared on
HTTP behavior, database mutations, and target-framework compliance rather than
source-code similarity to one preferred implementation.

## Status

Published benchmark, early and growing. The current suite is **v0: one lane
(`drf-fastapi`), eleven tasks, 170 verifiable endpoints**. Recorded results —
six models, with and without the Sanka engine, pass@1 — live at
[sanka.com/developer/bench](https://sanka.com/developer/bench). Numbers on
that page come only from runs whose frozen candidates, evaluator reports, and
full agent logs exist; nothing is estimated.

## Scoring

**Migration Quality Score = verified routes ÷ total routes in the lane's
suite, pass@1.** A route (here: an HTTP method-route) counts only when its
whole task passes every hard gate; a run that produces no bootable candidate
scores zero. Denominators are frozen per suite version and grow only by
adding tasks. Lanes are scored separately — framework, data, and object
lanes will never be blended into one number, because their route units are
not commensurable. Score changes bump the score version (current: v0.2).

Eleven synthetic fixtures exist. `drf-fastapi-001` covers CRUD and validation;
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

Baselines live at `baselines/<task>/<candidate>/`. The first fixture proves
the required controls:

| Baseline | Expected result |
| --- | --- |
| No-op | Fails target boot and native-target compliance |
| Sanka PR #13 compatibility bridge | Preserves behavior but fails the anti-proxy compliance gate |
| Native human reference | Passes behavior, database, regression, and native FastAPI gates |
| Sanka native converter (`sanka apply --bench-candidate`) | Passes every hard gate, including runtime native-target evidence |

`drf-fastapi-002` carries noop, compatibility-bridge, human
native-reference, and Sanka native-converter baselines. The converter's
envelope caught up with the fixture (sanka PR #17): its untouched
`--bench-candidate` output passes every hard gate, serving token
authentication natively without loading DRF.

Every fixture also carries two frozen coding-agent baselines —
`claude-code-alone` and `claude-code-with-sanka` — produced unattended by
`scripts/run_agent_candidate.py` with identical model, turn budget, and
contract (the with-Sanka prompt only adds that the Sanka CLI exists). Each
candidate's `GENERATED.md` discloses the prompt verbatim, turns, wall time,
and reported cost; `make report` renders those figures beside the tally.
Agent results are empirical, not pinned by tests — the report shows the
current state. The shared contract explicitly requires every evaluated
request to reach a workspace-owned FastAPI `APIRoute` (subclasses included); raw Starlette routes,
implicit framework redirects, mounts, and compatibility dispatchers do not
satisfy native-serving evidence in any arm.

Experiments may add a separately labelled
`*-with-sanka-readiness-aware` arm. Before the agent starts, the harness runs
`sanka scan` and `sanka plan`, freezes `sanka-readiness.json`, and emits a
scaffold only when native readiness reaches the configured threshold (50% by
default). Below it, the agent receives the structured unsupported/unscanned
route inventory and no scaffold. This diagnostic arm never replaces or
rewrites the official alone/with-Sanka pass@1 result.

`drf-fastapi-003` carries noop, compatibility-bridge, human
native-reference, and Sanka native-converter baselines. The converter's
envelope caught up again (sanka PR #21): writable nested serializers are
generated natively, and the author's transactional `create()` — business
rule, rollback and all — is carried over verbatim with its DRF exception
swapped for a native shim.

`drf-fastapi-004` carries noop, compatibility-bridge, human
native-reference, and Sanka native-converter baselines. The current converter
evidence was generated with the shipped engine (`sanka-cli` 0.1.8 /
`sanka-migrate` 0.1.0a10). The
bridge proxies the signals along with everything else, so it passes
behavior and database parity while failing the anti-proxy gate; the native
reference reimplements every signal side effect explicitly in a serving
process whose ledger app config never connects the source receivers. The
converter's native plan honestly reports 54% readiness — mixin-composed
viewsets and the `transfer` custom action are outside today's envelope —
and its untouched output fails evaluation at 5/17 behavior and 10/17 database
parity. Explicit 501 adaptation stubs keep native route evidence at 17/17, but
do not earn behavioral credit: the benchmark leads the converter again.

`drf-fastapi-005` carries the same four controls. The compatibility bridge
passes all 31 behavior and database comparisons but fails native serving
evidence; the native reference passes every hard gate. With the pinned
`sanka-cli` 0.1.8 / `sanka-migrate` 0.1.0a10 engine, the API root is generatable
but the six permission-matrix routes and custom review action require
adaptation. Native readiness is 12.5% (1/8), below the default 50% gate, so
apply emits a structured gap report rather than a scaffold. The frozen noop
outcome fails target boot rather than receiving a hand-written repair.

`drf-fastapi-006` also carries all four controls. The compatibility bridge
passes all 32 behavior and database comparisons but fails native serving
evidence, while the DRF-free reference passes every hard gate. The pinned
engine reports 14% native readiness: it drops 7 format-suffix aliases, marks
all 6 order CRUD routes `SANKA_DRF_SERIALIZER_SEMANTICS_UNSUPPORTED`, and can
generate only the API root. Because 14% is below the default 50% gate, apply
emits a structured gap report rather than a scaffold; the frozen noop outcome
fails target boot, and the nested serializer and transactional replacement
logic are not hand-repaired.

`drf-fastapi-007` carries the same four controls. Its compatibility bridge
matches all 30 HTTP and database outcomes but fails native serving evidence;
the DRF-free reference passes every hard gate. The pinned engine reports 14%
native readiness: it drops 7 format-suffix aliases, marks all 6 record CRUD
routes `SANKA_DRF_VIEWSET_OVERRIDES_UNSUPPORTED` because `retrieve()` and
`update()` are overridden, and can generate only the API root. Because 14% is
below the default 50% gate, apply emits a structured gap report rather than a
scaffold; the frozen noop outcome fails target boot, and cursor, filter,
representation, and conditional-response behavior is not hand-repaired.

`drf-fastapi-008` carries the same four controls. Its compatibility bridge
matches all 32 HTTP and database outcomes but fails native serving evidence;
the DRF-free reference passes every hard gate. The pinned engine reports 24%
native readiness: 7 of 29 non-alias routes are generatable, 7 format-suffix
aliases are dropped, and the remaining 22 routes require adaptation for legacy
view kinds. Because 24% is below the default 50% gate, apply emits a structured
gap report rather than a scaffold; the frozen noop outcome fails target boot
and no route is hand-repaired.

`drf-fastapi-009` carries all four controls. The compatibility bridge preserves
all 32 HTTP, database, and stored-file outcomes but fails native serving
evidence; the DRF-free reference passes every hard gate. The pinned a10 engine
reports 0% native readiness: nine serializer routes require
`SANKA_DRF_SERIALIZER_SEMANTICS_UNSUPPORTED`, three download routes require
`SANKA_DRF_CUSTOM_ACTION_UNSUPPORTED`, and apply emits no candidate. The honest
frozen outcome therefore fails target boot instead of receiving a hand-written
multipart or binary-response repair.

`drf-fastapi-010` carries all four controls. The compatibility bridge preserves
all 32 HTTP and two-table database outcomes but fails native serving evidence;
the DRF-free reference passes every hard gate. The pinned a10 engine reports 0%
native readiness: four routes require
`SANKA_DRF_VIEWSET_OVERRIDES_UNSUPPORTED` for the transactional create and
partial-update overrides, while the transition route requires
`SANKA_DRF_CUSTOM_ACTION_UNSUPPORTED`. Apply emits no candidate, so the honest
frozen native outcome fails target boot instead of receiving a hand-written
state-machine or optimistic-locking repair.

`drf-fastapi-011` carries all four controls. The compatibility bridge preserves
all 32 HTTP and database outcomes but fails native serving evidence; the
DRF-free reference passes every hard gate. The pinned a10 engine reports 0% native
readiness: the annotated list and grouped summary are unsupported non-viewset
view kinds, while all three transaction routes require
`SANKA_DRF_SERIALIZER_SEMANTICS_UNSUPPORTED` for their slug-related account
field. Apply emits no candidate, so the honest frozen native outcome fails
target boot rather than receiving hand-written aggregate logic.

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

1. **Hard tier (~5 tasks).** The first three tasks saturate at 100% for
   strong models; these are designed to break that, each targeting a
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
  --candidate-id claude-code-alone \
  --out baselines/drf-fastapi-001/claude-code-alone \
  --agent-bin ~/.claude/local/claude
# with-Sanka arms additionally take --sanka-bin <path to sanka>
```

The same harness can drive Codex against OpenAI or a supported
OpenAI-compatible provider. Codex runs use an isolated `CODEX_HOME`, the
Responses API, the provider's environment-variable API key, measured wall
time, and token-based cost only when explicit per-million prices are supplied:

```bash
uv run python scripts/run_agent_candidate.py \
  --agent codex \
  --agent-bin codex \
  --provider openai \
  --model gpt-5.3-codex \
  --task tasks/drf-fastapi/drf-fastapi-001 \
  --candidate-id codex-gpt-5-3-codex-with-sanka \
  --sanka-bin ../sanka/.venv/bin/sanka \
  --out baselines/drf-fastapi-001/codex-gpt-5-3-codex-with-sanka
```

The two official configurations share the same model, budget, and contract;
the ordinary with-Sanka prompt is strictly additive — it offers the Sanka CLI
with readiness-aware usage guidance. A third, diagnostic candidate id ending in
`-with-sanka-readiness-aware` adds a preflight threshold decision and frozen
gap checklist. The frozen overlay is graded by the same evaluator as every
other candidate.

For larger model matrices, use `scripts/run_agent_matrix.py` as the single
foreground coordinator. It preserves generated candidates across resumes,
drains their evaluations after a provider failure, records serving tiers with
`provider_variant`, and never activates a declared backup automatically. The
provider qualification and recovery contract is documented in
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
