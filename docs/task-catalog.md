# Task catalog

The suite has 17 tasks: 11 FastAPI migrations and 6 Flask migrations.
Each task directory contains its source, target contract and scenario definitions.

## FastAPI

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

## Flask

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
