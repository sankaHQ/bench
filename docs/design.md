# Implemented slices

## drf-fastapi-011: aggregates and related-row computed fields

The eleventh fixture makes query-derived response values observable across
pagination and mutations instead of treating them as serializer decoration.

- the two-row account list annotates total and pending transaction counts plus
  a filtered posted `Sum`, orders by those computed values with deterministic
  ties, and renders every Decimal at two places;
- `SerializerMethodField` values distinguish empty, pending, and settled
  accounts and expose the latest related reference. The evaluator checks both
  pages before and after creates, patches, deletes, and cross-account moves;
- the summary endpoint groups by region, includes account and transaction
  counts, preserves zero and negative totals, and returns an empty group list
  plus `"0.00"` when the fixture has no accounts;
- candidates see 7 scenarios and the evaluator grades a 32-scenario strict
  superset. Hidden cases cover computed ordering in both directions, page URL
  and tie stability, zero/negative/large totals, latest-row changes, rejected
  duplicate writes, mutation chains, empty accounts, and fully empty state. A
  visible-only scratch probe passes 7/7 public scenarios and fails 17/25 hidden
  scenarios;
- the native reference passes all 32 HTTP, database, side-effect, rerun, and
  serving checks. The compatibility bridge preserves the full contract but
  fails native evidence. With `sanka-cli` 0.1.8 and `sanka-migrate` 0.1.0a10,
  native readiness is 0%: two non-viewset aggregate routes and three
  slug-related serializer routes require adaptation, so apply emits no
  candidate and the frozen sanka-native outcome fails boot.

## drf-fastapi-010: state transitions and optimistic concurrency

The tenth fixture makes business-state legality, exact version progression,
and rejected-write atomicity part of the migration contract.

- `Order.status` follows one explicit graph: draft can submit or cancel,
  submitted can approve or cancel, approved can ship, and shipped/cancelled are
  terminal. The response includes the current state's ordered legal targets;
- PATCH and the custom `transition` action require a version. A successful
  write increments it exactly once and appends exactly one `OrderEvent`; a
  stale version returns 409 with expected/provided versions and changes neither
  table;
- the graded transition matrix covers every one of the 25 combinations of
  five source states and five target states. Legal moves return the updated
  representation; illegal moves return an exact 409 body with the ordered
  allowed list, while an unknown target remains a serializer-level 400;
- candidates see 7 scenarios and the evaluator grades a 32-scenario strict
  superset. The 25 hidden cases contain the remaining 23 matrix cells plus
  unknown-target validation and stale-transition rollback. A native scratch
  probe implementing only the visible branches passes 7/7 public scenarios and
  fails 25/25 hidden scenarios;
- the native reference passes all 32 HTTP, database, side-effect, rerun, and
  serving checks. The compatibility bridge preserves behavior and both tables
  but fails native evidence. With `sanka-cli` 0.1.8 and `sanka-migrate`
  0.1.0a10, native readiness is 0%: four viewset-override routes and the custom
  transition action require adaptation, so apply emits no candidate and the
  frozen sanka-native outcome fails boot.

## Coding-agent baselines

Frozen, fully disclosed agent candidates for every task: Claude Code run
headlessly with a fixed migration contract and the public scenarios, one
unattended attempt (infrastructure failures may be retried once, disclosed
verbatim in the candidate's provenance), same model and budget across the
alone/with-Sanka pair. Candidate schema v0.2 adds an optional ``stats`` block
(turns, wall time, reported cost) that the evaluator copies into result
provenance and the report renders beside the tally — the honest comparison
axis once capable agents pass the synthetic fixtures outright. The shared
deliverable contract discloses the tool-neutral native-serving rule: every
evaluated request must reach a workspace-owned FastAPI ``APIRoute`` rather
than a raw Starlette route, implicit framework redirect, mount, bridge, or
source-framework dispatcher.

The official comparison remains the two pass@1 arms above. A separate
readiness-aware diagnostic arm may preflight the same task with Sanka before
the agent runs. It freezes the plan-derived readiness decision and route gaps;
at the default 50% threshold it supplies only the unsupported and unscanned
route checklist instead of a low-readiness scaffold. The evaluator remains
tool-neutral and unchanged.

Result reports aggregate the already-recorded per-scenario HTTP, database, and
native-serving counters. They are explicitly diagnostic: the
v0.2 verdict is still task-level all-or-nothing, with no partial-credit or
compensating-score path.

## drf-fastapi-009: multipart files and explicit format negotiation

The ninth fixture makes request transport, stored bytes, and binary response
semantics part of the migration contract.

- a `ModelViewSet` collection accepts raw multipart requests and writes a
  Django `FileField`. The serializer allows `.csv`, `.json`, and `.txt`
  extensions case-insensitively, enforces a 32-byte ceiling, and records the
  original filename, media type, byte count, and SHA-256 digest;
- canonical, `.json`, and `.api` collection/detail/download routes are explicit
  URL patterns, so all 12 method-routes are counted by scan and served. The
  `.api` representation uses `application/vnd.sanka.file+json`; downloads stay
  binary and retain their stored media type plus exact `Content-Disposition`;
- the evaluation driver builds deterministic multipart bodies rather than
  relying on a client library, and normalizes declared binary responses as
  base64. Its side-effect ledger records path, size, digest, and bytes for every
  media file, making a database-only imitation insufficient;
- candidates see 8 scenarios and the evaluator grades a 32-scenario strict
  superset. The 24 hidden cases cover unusual and in-payload boundary tokens,
  suffix-specific uploads/downloads, both seeded files, case-insensitive
  extensions, 32-versus-33-byte limits, exact missing/blank/duplicate errors,
  missing objects, and mutation chains whose rejected writes must leave both
  tables and media files unchanged. A visible-only scratch probe passes all 8
  public scenarios and fails 13 of the 24 hidden scenarios;
- the native reference passes all HTTP, database, file-side-effect, rerun, and
  serving checks. The compatibility bridge preserves those behavioral outputs
  while its imported Django/DRF serving stack fails native evidence. With
  `sanka-cli` 0.1.8 and `sanka-migrate` 0.1.0a10, native readiness is 0%: nine
  serializer routes and three custom download routes require adaptation, so
  apply emits no candidate and the frozen sanka-native outcome fails boot.

## drf-fastapi-008: one domain across three legacy view styles

The eighth fixture makes mixed DRF routing styles and their URL semantics part
of one migration contract.

- the same `Entry` table and `ModelSerializer` are served through two
  `@api_view` functions, classic collection/detail `APIView` classes whose base
  explicitly performs DRF's dispatch lifecycle, and a router-backed
  `ModelViewSet`;
- function routes accept both slash forms, class routes canonically omit the
  slash, and viewset routes require it. Alternate class/viewset forms return
  exact 307 redirects in opposite directions, including their absolute
  `Location` values;
- regex detail captures accept `guide.v2+draft` and `release@2026.08`, proving
  the migration cannot silently substitute a slug converter. A formatted
  nested-regex route table is appended after the primary URL list in the style
  of large legacy Django applications; the source regression suite serves it,
  while scan reports `SANKA_DRF_DYNAMIC_ROUTE` for its four methods;
- request chains write through one style and read through another. Cross-style
  create, PATCH, PUT, and DELETE cases prove that all surfaces share one state
  model, while exact validation errors and database parity prove rejected
  writes do not persist;
- candidates see 8 canonical scenarios and the evaluator grades a 32-scenario
  strict superset. A scratch implementation of only the public surface passes
  all 8 visible cases and fails 20 of the 24 hidden cases;
- the native reference passes all 32 HTTP, database, side-effect, and serving
  checks. The compatibility bridge also preserves all HTTP/database outcomes
  but fails native evidence. With `sanka-cli` 0.1.8 and `sanka-migrate`
  0.1.0a10, the native plan reports 24% readiness: 7 of 29 non-alias routes are
  generatable, 7 aliases are dropped, and 22 routes require manual adaptation
  for legacy view kinds. Since readiness is below the default 50% gate, apply
  emits a structured gap report instead of a scaffold; the frozen noop outcome
  fails target boot.

## drf-fastapi-007: response-shape precision and stable cursors

The seventh fixture treats representation details as observable migration
behavior rather than presentation polish.

- a two-row `CursorPagination` envelope walks records by `-posted_at, -id`.
  Search and ordering filters compose on the same collection, and a custom
  ordering backend appends `id` in the requested direction so ties are stable;
- request chains prove that an encoded cursor obtained before a newer or
  middle-sorted insert still yields the same next logical page. Exact `next`
  and `previous` URLs preserve filter query parameters, and malformed cursors
  retain DRF's 404 body;
- `DecimalField` values remain strings with two places, including `"0.00"`
  and numeric input normalized to `"10.00"`. UTC and offset-aware inputs are
  rendered in the fixture's non-UTC `Asia/Tokyo` zone;
- detail and update responses use a SHA-256 validator over canonical serialized
  content plus exact `ETag`, `Cache-Control`, and `Vary` headers. Matching,
  wildcard, and comma-list `If-None-Match` branches return 304 with no body;
  a stale validator after PATCH returns 200 and the changed representation;
- candidates see 6 scenarios and the evaluator grades a 30-scenario strict
  superset. A visible-only native scratch probe passes all 6 public scenarios
  and fails 19 of the 24 hidden scenarios;
- the DRF-free reference matches all 30 HTTP and database results. The
  compatibility bridge also matches them but fails native serving evidence.
  With `sanka-cli` 0.1.8 and `sanka-migrate` 0.1.0a10, the native plan reports
  14% readiness: one API-root route emitted, seven aliases dropped, and all six
  record routes marked `SANKA_DRF_VIEWSET_OVERRIDES_UNSUPPORTED`. Since
  readiness is below the default 50% gate, apply emits a structured gap report
  instead of a scaffold and the frozen noop outcome fails target boot.

Query-bearing scenarios also pin a serving-guard correctness boundary: route
evidence matches on the URL path while the full URL, including its query
string, is still sent to the candidate. Otherwise a correctly served FastAPI
route would be misclassified as unrouted solely because `?cursor` was present.

## drf-fastapi-006: deep writable graphs and atomic replacement

The sixth fixture extends nested writes from one child level to a graph with
two independently constrained lists: `Order -> OrderItem -> Adjustment`.

- `POST`, `PUT`, and `PATCH` all accept the three-level graph. A supplied
  `items` list is a complete replacement, including on PATCH; a PATCH that
  omits `items` updates only root fields and preserves the existing nested
  graph, including every primary key;
- item SKUs are unique per order and adjustment codes are unique per item.
  These constraints are exercised during persistence rather than reduced to
  preflight-only validation, so a duplicate at the second item or second
  adjustment proves the surrounding `transaction.atomic()` rolls back the
  changed parent, deleted old graph, and already-created siblings;
- DRF 3.18's sparse string-index format is part of the HTTP contract. A bad
  second adjustment under the second item is returned as
  `{"items":{"1":{"adjustments":{"1":{...}}}}}`, with no placeholder
  entries for valid siblings;
- candidates see 7 scenarios and the evaluator grades a 32-scenario strict
  superset. The 25 hidden scenarios cover empty/default branches, errors at
  both list depths, mid-graph uniqueness, Nth-child rollback, PUT replacement,
  PATCH preservation, PATCH replacement, and rejected partial graphs. A
  visible-only scratch probe passes all 7 public scenarios and fails 25 of the
  25 hidden scenarios;
- the DRF-free reference reproduces all 32 response and database results. The
  compatibility bridge does the same through Django and therefore fails the
  native serving-evidence gate. With `sanka-cli` 0.1.8 and `sanka-migrate`
  0.1.0a10, the native plan reports 14% readiness: one API-root route is
  generatable,
  seven format-suffix aliases dropped, and all six order routes marked
  `SANKA_DRF_SERIALIZER_SEMANTICS_UNSUPPORTED`. Since readiness is below the
  default 50% gate, apply emits a structured gap report instead of a scaffold
  and the frozen noop outcome fails target boot.

## drf-fastapi-005: authentication and permission matrix

The fifth fixture turns the single-scheme auth surface from 002 into a
hard-tier ordering matrix with a visible/hidden split.

- one `ModelViewSet` runs an expiring database-token authenticator before
  `SessionAuthentication`; malformed, invalid, inactive, and expired token
  branches are distinct, and a bad token must stop evaluation before an
  otherwise valid session can authenticate;
- session-backed unsafe writes retain CSRF enforcement. The oracle pins a
  valid session+CSRF create and a missing-cookie 403 independently from token
  401 responses;
- `get_permissions()` selects `AllowAny` for list, `IsAuthenticated` for
  create, `IsAdminUser` for destroy and the custom `review` action, and
  `IsAuthenticated` plus an owner object permission for ordinary detail
  routes. Staff may destroy or review somebody else's object; owners who are
  not staff may not;
- the 401/403/404 cases prove evaluation order: authentication still runs on
  an `AllowAny` list; anonymous detail access fails before lookup; an
  authenticated missing detail reaches 404; and object permission failures
  happen only after a real detail object is loaded. Every case compares exact
  response bodies plus declared `WWW-Authenticate` and `Allow` headers;
- candidates see 7 scenarios while the graded evaluator runs a 31-scenario
  strict superset. The 24 hidden cases carry the malformed/expired/inactive
  variants, token-before-session traps, CSRF failure, missing-object ordering,
  owner denial without mutation, and token/session staff-action branches. A
  scratch candidate implementing only the seven public cases passes all seven
  and fails 16 of the 24 hidden scenarios.

All response formats were captured from the source application before the
native reference was written. The DRF-free reference reads the retained token
and session tables through Django's model layer, validates session hashes and
CSRF tokens natively, and passes all 31 scenarios. The compatibility bridge
also preserves all behavior but fails recorded serving evidence. With
`sanka-cli` 0.1.8 and `sanka-migrate` 0.1.0a10, the pinned converter reports
12.5% native readiness: the API root is generatable, while the six
permission-matrix routes and custom review action require adaptation. Since
readiness is below the default 50% gate, apply emits a structured gap report
instead of a scaffold and the frozen noop outcome fails target boot.

## drf-fastapi-004: signal-driven side effects, hidden scenario split

The fourth fixture is the first hard-tier task: its observable behavior
lives partly outside the views, in Django signals, and its graded scenario
set is deliberately wider than the public one.

- `post_save(LedgerEntry, created=True)` and `post_delete` receivers —
  connected in `AppConfig.ready` — keep an API-read-only `Account.balance`
  (via `F()` expressions) and an append-only `AuditLog` in step; the audit
  table has no writing endpoint but a read-only list endpoint;
- a custom `POST /accounts/{pk}/transfer/` action locks both accounts in pk
  order inside `transaction.atomic`, validates amount and funds, and writes
  two ledger entries plus one `transfer` audit row on success; insufficient
  funds must leave all three tables untouched (proven by database parity);
- deleting an account cascades its entries and fires the receivers per
  cascaded row in Django's descending-pk deletion order — the surviving
  audit rows pin that order;
- the driver supports request chains (`setup` requests before the graded
  request, each served in a fresh guarded process against the shared
  scenario database), which also forces real persistence between serving
  processes;
- the split: `public-tests/scenarios.json` carries 5 scenarios, the graded
  `evaluation/scenarios.json` a 17-scenario superset. The 12 hidden
  scenarios cover balance read-only enforcement, multi-entry `F()`
  composition, reverse postings on delete, rollback, transfer error shapes,
  audit ordering, cascade audit, and Decimal string forms. A visible-only
  probe passes all 5 public scenarios and fails 10 of the 12 hidden ones,
  so saturating the public surface no longer saturates the task.

All response formats were captured empirically from the live source
application before the native reference was written. The reference serves
through settings that install the ledger app via a plain `AppConfig`
(source receivers never connected) and reapplies every side effect
explicitly in the same transaction as its cause. The shipped converter
(`sanka-cli` 0.1.8 / `sanka-migrate` 0.1.0a10) honestly reports 54% native
readiness — mixin-composed viewsets and custom actions are outside the
envelope — and its frozen output fails at 5/17 behavior and 10/17 database
parity. Explicit 501 adaptation stubs keep native route evidence at 17/17,
but do not earn behavioral credit, so 004 ships without a passing converter
baseline.

## drf-fastapi-003: nested writes, transactions, validation edges

The third fixture covers the validation and transaction surface:

- writable nested serializers with DRF's index-keyed nested error format
  (`{"items": {"1": {"quantity": [...]}}}` — failing indices only), the
  list-type error, and combined order-level plus item-level errors;
- a transactional nested create: parent and children written inside
  `transaction.atomic`, then a business rule raises — the observable
  contract (400 plus an unchanged database) is enforced by the database
  parity gate, so a candidate that half-writes fails;
- `unique=True` model-message validation ("order with this reference already
  exists."), decimal digit/precision errors and string representation,
  choice-field errors, and cascade deletion.

All response formats were captured empirically from the live source
application before the native reference was written. With `sanka-cli` 0.1.8
and `sanka-migrate` 0.1.0a10, native readiness is 100% (7/7 non-alias routes).
The untouched converter output passes all 16 behavior, database, side-effect,
and native-serving comparisons.

## drf-fastapi-002: authentication and object permissions

The second fixture (`drf-fastapi-002`) covers the auth surface:

- database-backed `TokenAuthentication` (`rest_framework.authtoken`);
- `IsAuthenticated` plus the canonical author-or-read-only object permission;
- `perform_create` author injection;
- 401 variants (missing, invalid, malformed credentials), 403 on
  foreign-object writes, and `WWW-Authenticate`/`Allow` header parity via the
  scenario-level `capture_headers` contract (drivers and the serving guard
  capture a declared header subset into the compared response).

A native candidate must reimplement token authentication without loading DRF:
the token table stays, owned by the retained Django half, and the reference
implementation reads it through an unmanaged model mirror. Baselines are
noop, the Sanka compatibility bridge generated from merged Sanka main
(behavior passes — auth included — native gate fails on evidence), the human
native reference, and the untouched Sanka-native output. With `sanka-cli`
0.1.8 and `sanka-migrate` 0.1.0a10, native readiness is 100% (7/7 non-alias
routes) and the converter output passes all 13 comparisons without loading
DRF in the serving process.

Baselines are laid out per task: `baselines/<task-id>/<candidate>/`.

# Implemented v0.1 slice

This slice establishes the evaluator boundary before a converter or hosted API
is allowed to claim a successful DRF-to-FastAPI migration.

## Implemented

- JSON Schemas for tasks, candidates, and results.
- One pinned CRUD fixture with deterministic scenarios.
- Local and network-disabled, read-only Docker evaluation runners.
- Existing-test regression checks.
- Differential HTTP and SQLite row-state comparison.
- Runtime native-target compliance: every candidate scenario is served in a
  fresh guarded child process that arms a PEP 578 audit hook before candidate
  code loads. The hook cannot be removed once installed. It records imports of
  forbidden module prefixes (DRF and Django request-serving machinery),
  process creation, and socket connections. The guard also records whether the
  scenario was matched by a `fastapi.routing.APIRoute` whose endpoint code
  lives inside the candidate workspace. The guard observes and records rather
  than blocking, so facade candidates still demonstrate behavioral parity
  while failing the gate on evidence.
- Textual pattern checks demoted to result diagnostics over every
  candidate-contributed file (they previously gated on the entrypoint file
  only, which a helper-module facade trivially bypassed; the
  `tests/fixtures/obfuscated-bridge` control pins that bypass as caught).
- The native reference serves through DRF-free settings, proving the DRF
  request layer is genuinely absent from a native serving process while the
  retained Django test suite still exercises the source application.
- Two clean evaluation repetitions and variance detection; recorded serving
  evidence participates in the determinism fingerprint.
- No-op, Sanka compatibility-bridge, native human-reference, and frozen
  Sanka-native baselines for every task.

## Deliberate limits

- The fixture covers one model and CRUD behavior only.
- Scenarios are served through an in-process ASGI test client, not through
  independently booted server processes.
- The serving guard defends against converters that Goodhart the visible
  checks, not against deliberate audit-hook evasion; adversarial custody
  belongs to the future hidden evaluator.
- Side-effect ledgers are represented in the result contract but the first
  fixture has no Celery, email, file, signal, or webhook scenario.
- The public evaluator material is visible to candidates. A future Verified set
  must mount hidden tests only after the candidate is frozen.
- Docker build dependency resolution is pinned by `uv.lock`; the evaluation run
  itself has no network.
- No hosted execution, repository upload, leaderboard, API route, or product
  integration is included.

## Next implementation gates

1. Add transaction-rollback, nested-write, and side-effect fixtures
   (authentication and object permissions landed as `drf-fastapi-002`);
   extend the Sanka converter's native envelope to pass 002.
2. Replace public-only task execution with a private hidden-evaluator mount and
   signed result manifest.
3. Integrate the shared result schema into `sanka verify` without letting Sanka
   select or bypass evaluator assertions.
4. Design the separately reviewed `/v2/migrate/code-projects` and
   `/v2/migrate/code-migrations` API resources.

## Measurement fixes from the v3 model-matrix forensics (2026-08-31)

The 10-task model matrix (2026-08-30) surfaced measurement hazards that
distorted the alone/with-Sanka comparison. Each fix below changes how cells are
measured, so results produced before and after are not silently comparable —
the agent-harness prompt and the driver evidence are part of the recorded
provenance (GENERATED.md carries the prompt verbatim; task digests cover the
drivers).

**Side-effect parity is now measured, never declared.** Every scenario driver
snapshots its served workspace before the scenario and reports the files the
application created, modified, or deleted (`sanka_bench.workspace_effects`),
for the oracle and the candidate symmetrically. Previously nine of ten drivers
hardcoded `side_effects = []`, which made the gate an assertion-free tautology;
a candidate that quietly wrote files into its workspace could not fail it.
Media-serving tasks keep their richer media-state evidence and add the
workspace probe on top. Only change kinds enter the evidence, so files whose
contents legitimately vary between clean runs still fingerprint identically
for the determinism gate.

**`APIRoute` subclasses are native (evaluator 0.0.3).** The gate asks whether the
serving route *is* a FastAPI `APIRoute` (`isinstance`) with its endpoint in the
workspace, not whether its class is named exactly `fastapi.routing.APIRoute`. Three
v4-era candidates subclassed `APIRoute` only to override `matches()` so the workspace
endpoint could reproduce DRF's resolve-path-then-405 order, and added a
`/{name:path}` route to mirror Django's 404 body; the exact-name check rejected them
although nothing about them was a bridge. The evidence keeps the concrete class name
(`route_class`), adds `route_is_apiroute` and the matched `route_path`, and the
report lists scenarios that a catch-all route served although the source answered
something other than 404 under `diagnostics.catch_all_served_scenarios` — a
diagnostic, never a gate. Evidence recorded before 0.0.3 has no `route_is_apiroute`
and keeps the exact-class reading, so old reports keep their verdicts. The agent
prompt is unchanged: it already says "served by a FastAPI `APIRoute`".

**Included routers resolve to the route that serves (evaluator 0.0.2).** FastAPI
0.141, the version pinned since the first commit, keeps `app.include_router(router)`
targets as lazy `fastapi.routing._IncludedRouter` entries in `app.routes` instead
of copying the router's `APIRoute` objects. The serving guard recorded that wrapper
as the matched route: it has no endpoint, so every candidate built the ordinary
FastAPI way (a router module plus `include_router`) was reported as served by a
non-`APIRoute` class with its endpoint outside the workspace, and failed the native
gate on every scenario while behaviour, database and side-effect parity passed. The
guard now walks the wrapper's effective candidates with the request scope and
records the underlying route, recursing through nested and prefixed includes; raw
Starlette routes, mounts and bridges are still recorded as themselves and still fail.
Reports carry `evaluator_version` `0.0.2` from this change, so a re-evaluation of a
frozen candidate is distinguishable from its original verdict. Frozen matrix rows are
never rescored in place; a corrected verdict is published as a labelled
re-evaluation beside the original.

**Budget exhaustion is graded; infrastructure death is classified.** The agent
harness previously discarded any run whose agent reported an error — including
`error_max_turns` — so a turn-capped workspace that might have passed scored
zero without ever being evaluated, and a silent provider failure that produced
no files was indistinguishable from an agent refusal. Now: turn-budget and
wall-clock exhaustion freeze the workspace as-is with the terminal reason
disclosed in GENERATED.md (exit 0, evaluated like any candidate); other agent
errors remain unfrozen failures (exit 1); an empty workspace exits 3 with the
recorded turn count so the run driver can classify silent provider failures
into the infrastructure ledger instead of the quality columns. The Codex CLI
exposes no turn bound, so codex cells are bounded only by the wall-clock
timeout — GENERATED.md now states which limit actually applied instead of
implying a turn cap that never reached the agent. If Claude returns success
while reporting more turns than the requested limit, the candidate is frozen
once and the overrun is disclosed as a protocol deviation instead of being
mislabelled as completed within budget.

The parsed result event, not the process exit code, decides which of these
paths applies. Claude Code exits 1 on `error_max_turns` while still printing
a complete result; a runner revision that treated any non-zero exit as an
agent-run failure before reading the result silently discarded every
turn-capped Claude workspace it saw (the ten unevaluated v4 cells all ran
under that revision). Only a non-zero exit *with no parseable result* is an
agent-run failure now, the test double exits 1 whenever it reports an error
so the real CLI contract is what the suite pins, and Claude runs are captured
as `stream-json` so `agent-log.jsonl` is the per-turn transcript rather than
a copy of the final result line.

**Sanka runs in the fixture dependency environment.** The Sanka console script
may be isolated in an engine virtualenv, but its DRF scanner imports the source
project. With-Sanka arms pass the benchmark interpreter's installed-package
paths to the scanner and agent process, preventing model-specific
``PYTHONPATH`` repairs from becoming an accidental part of the treatment.

**The grading basis is disclosed to the agent.** The prompt now states that
`public-tests/scenarios.json` is a representative sample and that the evaluator
replays a hidden superset with additional edge cases and captured response
headers. The hidden scenarios themselves stay hidden; what changed is that an
agent can no longer satisfy the letter of the prompt ("verify every scenario")
while remaining blind to the dimension it is graded on.

**The with-Sanka condition offers the tool; it no longer mandates a workflow.**
The old paragraph instructed agents to copy the complete generated overlay to
the repository root and adjust it — including on tasks where the engine's own
plan reported 0–14% native readiness and emitted almost nothing. Forensics
across three models showed the mandate displaced source reconnaissance and
licensed early confidence without contributing code. The new paragraph tells
the agent to read the plan's readiness report, adopt generated files where
readiness is high, treat low-readiness output as reference material, and in
all cases derive exact semantics from the source application, which remains
the specification. The condition still differs from `alone` by exactly one
additive paragraph.

**Near-misses are visible beside the cliff.** `sanka-bench report` now renders
a diagnostic scenario-parity table (Migration Quality Score v0.3 preview):
per-scenario behavior/database/native pass rates summed across covered tasks,
plus per-task scenario counts in the gate matrix. The headline stays binary
per task — a 36-route task is still all-or-nothing — but a candidate at 31/32
scenarios is now distinguishable from an empty one without reweighting or
blending anything into the verdict.

## Task-sharded baseline CI

Baseline evaluations are independent only at the task boundary: every
task/candidate pair already receives isolated temporary workspaces and a
task-specific report path, while a single evaluator run owns its scenario
sequence and determinism repetitions. CI therefore shards the ten task suites
across GitHub-hosted runners with a bounded five-task concurrency limit instead
of starting multiple evaluators inside one two-core runner.

The stable required checks remain `check` and `docker-baselines`. Each is an
aggregate gate over its underlying unit/local or Docker task shards, so branch
protection still fails closed when any shard fails or is cancelled. The
Makefile retains the full sequential `baselines` and `docker-baselines` targets
for local control-set proof and exposes task-scoped targets such as
`baselines-008` and `docker-baselines-008` for CI.

Docker evaluator images are content-addressed from the repository tree. A task
shard builds its image on the first candidate and reuses that exact local image
for the remaining candidates; a changed task, candidate, lockfile, or evaluator
source produces a different tag. Evaluation containers keep the existing
network, filesystem, capability, memory, CPU, and process isolation controls.
