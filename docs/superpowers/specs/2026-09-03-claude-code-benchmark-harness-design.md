# Claude Code benchmark harness design

**Date:** 2026-09-03

## Decision

Use Claude Code as the only coding-agent harness for the official Sanka benchmark
matrix. Keep the evaluator tool-neutral and keep the existing matrix coordinator,
immutable cell artifacts, pass@1 rules, provider limits, and infrastructure-retry
ledger.

The harness and the inference treatment are different things:

- **Harness:** the pinned Claude Code executable, flags, tool permissions, prompt,
  project skill surface, turn and wall-clock budgets, workspace rules, and transcript
  parser.
- **Treatment:** the requested model, actual serving provider, endpoint, authentication
  and billing mode, serving variant, and exact model revision returned by that route.

Claude subscription runs use Claude Code's native OAuth login and Anthropic route.
API-key and gateway runs use the gateway's credentials, never subscription OAuth.
Anthropic documents third-party LLM gateways, but does not support routing Claude Code
to non-Claude models through them. GPT and other non-Claude routes therefore remain
explicitly labelled experimental gateway treatments until they pass the qualification
contract below. CLIProxyAPI is one possible gateway treatment, not a trusted default or
an Anthropic-supported route.

No scored paid run starts as part of implementing this design. Exact model IDs,
qualified routes, and the authorized spend scope are separate launch decisions.

## Goal

Measure whether giving the same AI coding harness the Sanka CLI and its official skill
improves migration development outcomes. The benchmark must answer three questions for
each model:

1. Does Sanka improve verified migration quality at pass@1?
2. Does Sanka reduce agent development time for the quality achieved?
3. Does Sanka reduce token use or cost for the quality achieved?

The result is a paired comparison, not a leaderboard of unrelated harnesses.

## Non-goals

- Replacing or special-casing the evaluator for Sanka output.
- Building a new agent framework when Claude Code already supplies the tool loop.
- Treating a requested model name as proof of the model that actually served a run.
- Converting subscription access into a per-request cash price.
- Uploading raw transcripts, secrets, or per-run sandboxes.
- Making the diagnostic readiness-aware lane part of the official two-lane score.

## Approaches considered

### A. Claude Code for every model — selected

All official cells invoke the same pinned Claude Code CLI. Native Claude models use the
Anthropic route. Other models use a declared Anthropic-protocol gateway treatment after
qualification.

This best isolates the Sanka treatment because the agent loop, tools, permissions, and
transcript format remain constant. Its limitation is important: a non-Claude gateway
route is not supported by Anthropic, so each route needs stronger identity and behavior
evidence and must not be described as an official Claude Code provider integration.

### B. Keep Claude Code for Claude and Codex CLI for other models

This is closest to the current code and uses provider-native clients, but changes the
tool loop, prompting behavior, sandbox semantics, and budget enforcement alongside the
model. It is useful as a separately labelled harness study, not for the primary Sanka
benefit claim.

### C. Build a custom provider-neutral agent harness

This could normalize every provider at the protocol level, but it would create a new
agent product whose tool behavior must itself be validated. That work does not improve
the immediate benchmark claim and is out of scope.

## Experimental unit and lane contract

A cell remains `(task, model treatment, configuration, sample)`. Official
configurations are:

- `alone`: Claude Code receives the core task prompt. The Sanka binary, Sanka skill,
  Sanka state, and Sanka-specific prompt are absent.
- `with-sanka`: the same Claude Code build, model treatment, task, prompt core, tool
  permissions, turn budget, and wall-clock budget are used. Before the agent starts,
  the harness installs the pinned project-local skill with
  `sanka skill install claude --scope project` and exposes the pinned `sanka` binary.
  A short prompt sentence states that Sanka is available; usage instructions live in
  the installed skill.

The agent is not forced to call Sanka. Choosing whether and how to use the product is
part of the treatment being measured. Extension installation needed to make the pinned
CLI usable is environment preparation and is identical across all with-Sanka cells.

The existing `with-sanka-readiness-aware` configuration remains diagnostic. Any
pre-agent scan, plan, or scaffold makes it a different treatment, so it cannot replace
or be pooled with the official `with-sanka` lane.

Samples are independent pass@1 attempts. The prompt, evaluator, source, model treatment,
and budgets are pinned across the pair. Configuration order is balanced across samples
so provider load or warm-cache order does not consistently favor one lane.

## Reuse of the current runner

The implementation extends the three existing scripts instead of adding another
orchestrator:

- `run_agent_matrix.py` keeps foreground scheduling, provider and model concurrency
  caps, cell-state recovery, single-writer aggregation, and the disclosed one-time retry
  for a provider incident that produced no model output.
- `run_matrix_cell.py` keeps manifest enforcement, environment allowlisting, per-cell
  generation/evaluation phases, and pinned Sanka toolchain checks.
- `run_agent_candidate.py` becomes the single Claude Code cell harness for official
  matrices and retains raw stream-JSON capture, candidate freezing, and disclosure.

The current Codex path is not used by official matrices. Removing it is preferable once
the Claude gateway qualification fixtures cover the non-Claude routes; until then it may
remain only as a non-official compatibility path, clearly excluded by manifest
validation from an official Claude-harness run.

## Run manifest

Each model entry declares one immutable treatment:

```json
{
  "slug": "gpt-5-6-via-cliproxyapi",
  "candidate_slug": "claude-code-gpt-5-6",
  "harness": "claude-code",
  "requested_model_id": "<exact requested id>",
  "provider": "<actual inference provider>",
  "provider_variant": "<serving tier or deployment>",
  "route_kind": "gateway",
  "gateway_profile": "cliproxyapi-anthropic-v1",
  "billing_mode": "api_key",
  "qualification": "qualifications/<digest>.json"
}
```

Native subscription entries use `route_kind: anthropic-native` and
`billing_mode: subscription`; they do not name or load gateway credentials. A change to
the model revision, provider, endpoint, gateway version, protocol adapter, serving tier,
quantization, billing mode, Claude Code version, prompt, Sanka skill, or Sanka CLI starts
a new treatment and therefore a new run fingerprint.

The manifest also pins:

- benchmark commit and agent-runner digest;
- Claude Code version and executable digest;
- task source and evaluator digests;
- core prompt and Sanka prompt-addon digests;
- turn and wall-clock budgets;
- Sanka CLI version, extension version, and installed skill digest;
- price-card source and effective date when derived API cost is allowed;
- sample count, concurrency policy, and exact paid-run authorization scope.

## Provider and model qualification

Qualification runs before scored generation and uses a disposable, non-task workspace.
It is not silently repeated inside a scored cell. A treatment is qualified only when
one probe record proves all of the following:

1. The pinned Claude Code executable starts non-interactively with the exact benchmark
   flags and isolated configuration.
2. The route accepts the requested model identifier and returns a successful terminal
   result.
3. A tool call creates and reads a known file, proving the Claude Code tool loop works
   through the route.
4. Streaming emits parseable assistant, tool, and terminal events.
5. The actual backend model identity is independently available from provider or
   gateway evidence and matches the manifest. A Claude-shaped alias in the client
   transcript is insufficient for a non-Claude backend.
6. Input, cache, and output usage fields can be reconciled with provider or gateway
   readback. If the provider has no immediate readback, the probe records that limitation
   and the treatment cannot publish a dollar-cost claim.
7. Timeout and provider-error behavior can be classified without mistaking a model
   quality outcome for infrastructure failure.

The qualification record contains hashes of the probe prompt, transcript, gateway
configuration without secrets, provider readback, and Claude Code version. A model
identity mismatch, unknown backend, unsupported tool behavior, or missing terminal event
blocks that treatment before paid benchmark authorization.

## Per-cell sandbox

Every cell receives a unique sandbox rooted under its run directory:

```text
sandboxes/<candidate-id>/
  workspace/
  claude-config/
  sanka-home/        # with-Sanka only
  raw/
```

The workspace starts from the pinned task source and public tests. Claude project state,
session data, and settings are isolated per cell. The native subscription credential may
come from the machine's authenticated Claude login, but project memory and run artifacts
must not be shared. Gateway cells receive only the allowlisted variables for their named
profile.

The alone lane uses a sanitized path and workspace with no project Sanka skill or Sanka
home. The with-Sanka lane receives a cell-local copy of the prepared, pinned Sanka state,
then installs the skill project-locally. The harness records the installed skill path and
digest before launching Claude Code. Generated `.claude` and `.sanka` control files are
run evidence, not candidate implementation files, and remain outside the evaluated
overlay.

The sandbox is retained with the run artifacts for diagnosis and resume. A scored
candidate is frozen to its overlay and hashes; evaluation can be rerun without another
model call. An authorized infrastructure retry starts from a clean attempt-2 sandbox,
while attempt 1 moves intact into the existing incident ledger.

## Cache and resume semantics

The current durable cell states are the cache. No remote cache service or duplicate
cache database is needed.

Each cell adds an `input_digest` computed from the immutable inputs listed in the
manifest. Generation writes that digest before the model request and the terminal
artifact writes it again with output hashes. On resume:

- matching `generated` cells are evaluated first without model access;
- matching `terminal` cells are skipped and never overwritten;
- `untouched` cells may start only under the foreground coordinator and exact
  authorization scope;
- a path whose recorded digest differs from the manifest is `ambiguous`, never a cache
  hit;
- quality failures remain terminal and are never retried;
- the existing one-time provider-incident retry remains allowed only when attempt 1
  produced no model output and its evidence is preserved.

A changed input gets a new run directory or candidate identity. The harness never
mutates old results to make them fit a new manifest.

## Telemetry and cost contract

Raw Claude Code stream JSON remains the canonical client transcript. The parser also
writes a normalized per-cell record containing:

- requested and actual model identity;
- provider, provider variant, route kind, gateway profile, and billing mode;
- Claude Code, Sanka CLI, extension, and Sanka skill versions/digests;
- task, prompt, evaluator, manifest, input, candidate, transcript, and report digests;
- start/end timestamps, agent wall time, lane setup time, evaluation time, and terminal
  reason;
- turns; input, cache-creation, cache-read, and output tokens per actual model plus
  totals;
- Claude Code reported cost, provider-reported cost, derived cost, and one selected
  `cost_usd` with an explicit basis;
- wave ID, admitted concurrency, stage makespan, attempt number, and prior incident
  reference;
- evaluation status, verified routes, hard-gate results, and failure classification.

Cost rules:

- For API-key runs, prefer provider billing readback. If unavailable, derive cost only
  from recorded tokens and a pinned price card for the exact provider treatment.
- For subscription runs, actual marginal request cost is `null`. Claude Code's reported
  API-equivalent cost may be retained in a separate field but is never presented as the
  subscription charge.
- For gateway runs, never use a different provider's public price merely because the
  requested model name matches. Provider readback or that gateway treatment's pinned
  price basis is required.
- Missing cost never becomes zero. Missing token classes remain `null` and are disclosed.

The run aggregate is rebuilt by the existing single foreground writer from immutable
cell records. No external analytics service is needed initially. Raw and normalized
artifacts stay local; only scrubbed, hash-linked summaries may be published after
approval.

## Speed and benefit reporting

Quality remains the hard boundary: fully migrated task count, pass rate, and the existing
route-weighted score are reported first. Time and cost cannot compensate for a failed
native-serving or behavioral gate.

For each model and lane, report:

- agent wall seconds per task-sample;
- end-to-end seconds, with setup and evaluation shown separately;
- input/cache/output tokens and total tokens;
- cost per task-sample and cost per verified route when cost is known;
- agent seconds per verified route;
- suite makespan and concurrency, labelled as operational throughput rather than model
  speed.

The Sanka effect is computed from paired task-samples for the same model treatment.
Publish the quality delta together with paired time, token, and cost deltas and their
intervals. A faster failed attempt is not a productivity win. The supported claim is
therefore one of:

- higher verified quality at equal or lower time/cost;
- equal verified quality at lower time/cost; or
- an explicit quality/time/cost tradeoff.

Do not collapse these dimensions into one opaque score.

## Credentials and artifact safety

The implementation adds `.env` and run directories to the repository ignore rules while
retaining a tracked `.env.example` containing names only. The cell driver reads only a
fixed allowlist from the manifest's `env_path`; credential values never appear in command
arguments, manifests, logs, disclosures, digests, or normalized telemetry.

Native subscription and gateway profiles are mutually exclusive. Gateway variables are
removed from native subscription cells, and Anthropic API variables are removed when the
profile does not require them. Before aggregation or publication, the runner scans the
manifest, logs, transcripts, sandboxes, candidates, reports, and incident ledger for
known credential values and common key patterns. A hit blocks publication.

The existing untracked local `.env` is not read or changed while implementing this
design. Ignoring it is a repository change; populating it remains an operator action.

## Failure classification

- **Model quality:** completed or budget-exhausted pass@1 run with model output. Freeze
  and evaluate it; never retry.
- **Provider infrastructure:** authenticated provider error, capacity/rate-limit event,
  or gateway outage with no model output. Preserve evidence and apply only the existing
  one-time explicitly disclosed retry rule.
- **Harness failure:** Claude Code crash, unparseable terminal semantics, tool-loop
  failure, or sandbox violation. Do not score; stop admissions and investigate.
- **Identity failure:** actual model cannot be proved or differs from the manifest. Do
  not score or substitute another route.
- **Evaluator failure:** generated candidate exists but evaluation infrastructure fails.
  Keep the candidate and rerun evaluation without model access.
- **Ambiguous:** artifacts disagree. Stop and require operator classification.

## Delivery slices

1. Tighten the manifest around a pinned Claude Code harness and qualified route records;
   make official matrices reject mixed harnesses.
2. Add per-cell Claude/Sanka isolation and project-local Sanka skill installation while
   preserving the current candidate overlay contract.
3. Add input digests and normalized usage/cost telemetry to the existing immutable cell
   artifacts and resume logic.
4. Extend reports with paired time, token, cost, and quality views.
5. Run free/local fixtures, then one non-scored qualification probe per route. Request
   exact model and paid-scope approval only after those probes pass.

## Acceptance criteria

- An official manifest cannot contain a harness other than the pinned Claude Code build.
- Every model treatment has qualification evidence for tool use, terminal parsing,
  actual model identity, and usage accounting before paid cells are authorized.
- Every cell has a distinct workspace and Claude configuration; only the with-Sanka
  lane contains the pinned project-local Sanka skill and Sanka runtime.
- The two official lanes differ only by the declared Sanka treatment.
- Resume performs no model call for matching generated or terminal cells and refuses a
  stale digest as a cache hit.
- Every terminal cell preserves raw transcript, normalized telemetry, candidate/report
  hashes, timing, usage, cost basis, wave metadata, and failure classification.
- Subscription cost is not misrepresented as a per-call cash charge; unknown cost is
  never zero.
- Quality, time, tokens, and cost are reported per model and as paired lane deltas.
- The evaluator and hard-gate scoring remain tool-neutral and unchanged by harness
  routing.
- A secret scan and artifact-count/hash check pass before any result is published.
