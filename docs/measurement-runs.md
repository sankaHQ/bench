# Reliable Claude Code model-matrix runs

Official measurements are paired pass@1 experiments: the same pinned Claude
Code harness runs each model treatment once without Sanka and once with the
project-local Sanka skill. The evaluator stays tool-neutral. A run never swaps
harnesses, models, providers, or routes to fill a failed cell.

Implementing or testing this runner does not authorize a paid model call. A
scored run additionally requires the exact authorization recorded in its
manifest.

## Manifest v2

Use `sanka-bench/model-matrix-run-manifest/v2` and exactly these official
configurations:

```json
"configurations": ["alone", "with-sanka"]
```

Every model entry pins one inference treatment:

```json
{
  "slug": "gpt-via-example-gateway",
  "candidate_slug": "claude-code-gpt-via-example-gateway",
  "harness": "claude-code",
  "requested_model_id": "gateway-model-alias",
  "actual_model_id": "provider-confirmed-model-revision",
  "provider": "example-provider",
  "provider_variant": "serving-tier-or-deployment",
  "route_kind": "gateway",
  "billing_mode": "api_key",
  "gateway_profile": "example-anthropic-v1",
  "qualification": "qualifications/example.json",
  "qualification_sha256": "sha256:..."
}
```

Native Claude subscription entries use `route_kind: anthropic-native`,
`billing_mode: subscription`, and `gateway_profile: null`. Gateway entries use
`route_kind: gateway`, `billing_mode: api_key`, and a named profile. A changed
model revision, route, provider variant, Claude binary, prompt, evaluator,
Sanka CLI, extension, skill, budget, or sample number changes the cell input
digest and is not a cache hit.

The manifest also pins the benchmark SHA, tool paths and digests, task weights,
sample count, concurrency policy, and exact `authorization_scope`. Generation
starts only when `authorization.paid_run_authorized` is true, the authorization
scope matches, and the named worktree is clean at the exact SHA.

## Qualify each route first

Qualification is a separate, non-scored provider call. Prepare a provider
evidence JSON object containing `provider`, `provider_variant`,
`actual_model_id`, and `usage_accounting: true`, then run:

```bash
uv run python scripts/qualify_claude_route.py \
  --claude-bin /absolute/path/to/claude \
  --requested-model-id MODEL_ID \
  --provider PROVIDER \
  --provider-variant VARIANT \
  --route-kind gateway \
  --billing-mode api_key \
  --gateway-profile PROFILE \
  --provider-evidence /absolute/path/to/provider-evidence.json \
  --output /absolute/path/to/run/qualifications/route.json
```

The probe must prove Claude Code tool use, stream parsing, a successful terminal
event, usage accounting, and the actual backend identity. Hash the resulting
qualification JSON into the manifest. A requested alias alone is not model
identity evidence.

## Credentials

Native subscription cells use the machine's Claude login and deliberately
remove `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, and `ANTHROPIC_API_KEY`.
They do not require an env file.

Gateway cells read only these names from the manifest's `toolchain.env_path`:

```dotenv
ANTHROPIC_BASE_URL=
ANTHROPIC_AUTH_TOKEN=
ANTHROPIC_API_KEY=
```

Copy `.env.example` outside the run artifact directory, fill the base URL and
exactly one authentication value, keep the file untracked, and point the
manifest at its absolute path. Credentials never belong in a command, manifest,
transcript, or report.

## Sandboxes, skill, and resume

Each cell keeps its own recoverable sandbox:

```text
sandboxes/<candidate-id>/
  workspace/
  claude-config/
  sanka-home/        # with-Sanka only
  raw/
```

The alone lane has no Sanka binary, state, skill, or Sanka-specific prompt. The
with-Sanka lane copies the prepared pinned Sanka state and runs
`sanka skill install claude --scope project --project-dir <workspace>` before
Claude Code starts. The installed path and `SKILL.md` digest are recorded. The
agent receives only a short sentence saying that Sanka is available.

The current cell states are the cache; there is no second cache database:

1. `untouched` may generate under the authorized foreground coordinator;
2. `generated` is evaluated first on resume without another model call;
3. `terminal` is immutable and skipped;
4. `ambiguous` has missing or conflicting evidence and blocks resume.

The input digest is written before the request. A stale digest is ambiguous,
not reusable. A provider incident with no model output may receive the one
disclosed attempt-2 retry declared by the manifest; quality failures never do.

## Run the coordinator

The cell command template may use `{python}`, `{manifest}`, `{phase}`, `{task}`,
`{task_suffix}`, `{model}`, `{config}`, `{provider}`, `{provider_variant}`,
`{sample}`, and `{candidate_id}`.

```bash
uv run python scripts/run_agent_matrix.py \
  --manifest /absolute/path/to/run/run-manifest.json plan

uv run python scripts/run_agent_matrix.py \
  --manifest /absolute/path/to/run/run-manifest.json run \
  --stage-id calibration \
  --provider-cap 1 \
  --model-cap 1 \
  --evaluation-cap 1
```

Use repeated `--cell task:model:configuration` arguments for a calibration
subset. Omit them only after the route and evaluator limits are healthy.

If generation fails, the coordinator stops admitting paid requests and drains
evaluation for already-generated candidates. The raw Claude stream remains the
canonical transcript. Normalized `telemetry.json` records model and route
identity, timing, token classes, cost basis, wave, attempt, and transcript,
overlay, and report hashes.

## Cost and reporting

- API-key runs use Claude Code's reported cost unless provider readback or a
  pinned treatment-specific price basis supersedes it.
- Subscription runs keep actual marginal `cost_usd` as null. Claude Code's
  estimate is reported separately as API-equivalent cost, never as money spent.
- Gateway cost must use that gateway treatment's evidence. A similarly named
  model on another provider is not a valid price source.
- Missing cost and token classes stay null; they never become zero.

Reports lead with verified quality, then show agent time, token classes, actual
cost, API-equivalent cost, and seconds/cost per verified route. Paired deltas
compare only the same model treatment, task, and sample. The diagnostic
readiness-aware arm is excluded.

Before aggregate output is written, the coordinator scans the run artifacts
for known credential values and provider-key patterns and validates each
generated/terminal cell's input, transcript, overlay, candidate, and report
hashes. A secret or integrity issue emits `publication-gate-failed` with paths
only and skips aggregation. Raw transcripts and sandboxes remain local; publish
only reviewed summaries.

## Recovery checklist

1. Prove no coordinator or workers remain.
2. Keep the failed log, raw transcript, sandbox, candidate, and report intact.
3. Classify every cell as terminal, generated, untouched, or ambiguous.
4. Evaluate generated cells without model access.
5. Record the incident and exact approved retry scope.
6. Resume untouched cells on the same treatment, or create a new labelled
   treatment and authorization.
7. Rebuild aggregates only after the credential and artifact gates pass.
