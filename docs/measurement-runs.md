# Reliable model-matrix runs

Model-matrix measurements are pass@1 experiments, not a best-of retry loop.
Reliability therefore means preserving paid evidence and separating provider
failures from model quality. It does not mean silently moving a cell to another
serving stack.

## Durable cell states

Every cell progresses monotonically:

1. `untouched` — no model request has started;
2. `generated` — the pass@1 candidate and successful generation marker exist;
3. `terminal` — evaluation completed, or generation ended with classified
   infrastructure evidence;
4. `ambiguous` — artifacts disagree and require operator classification.

A resume evaluates `generated` cells before admitting new model requests. It
never overwrites a generated or terminal cell. Workers write only their own
candidate, report, and log; one foreground coordinator writes aggregate files.

Codex JSONL can contain recoverable top-level `error` notices followed by a
successful `turn.completed`. The final terminal turn event is authoritative:
`turn.completed` succeeds, `turn.failed` fails, and a transcript with neither
is an infrastructure ambiguity. The process exit code remains an independent
hard check.

If generation fails, the coordinator stops admitting new paid generations but
drains evaluation for every already-generated candidate. This prevents a
provider incident from stranding completed work or causing an accidental
second model call.

One class of failure may be retried without an operator: a provider incident
that produced no model output. When the manifest declares
`execution.auto_retry` with `patterns` (case-insensitive substrings such as
`at capacity`, `rate limit`, `overloaded`) and an optional `backoff_seconds`,
a failed generation whose driver log ends in a matching `agent reported an
error` line and whose candidate has no overlay is moved into
`incidents/auto-retry/<candidate>/attempt-1/`, recorded in `incident.json`,
authorized as attempt 2 in `execution.infrastructure_retries`, and generated
once more after the backoff. The cell driver passes `--attempt 2
--prior-failure` to the agent runner, so GENERATED.md discloses the retry. A
second failure, an unmatched error, a previously retried cell, or any attempt
that left candidate files halts admissions exactly as before. Quality failures
never qualify: they end with a candidate and a report.

The coordinator receives an explicit manifest and a cell-driver command. The
command template may use `{python}`, `{manifest}`, `{phase}`, `{task}`,
`{task_suffix}`, `{model}`, `{config}`, `{provider}`, and
`{provider_variant}`. Paid execution additionally requires a clean worktree at
the exact `benchmark_sha` and an authorization whose scope exactly matches
`execution.authorization_scope`.

```bash
python scripts/run_agent_matrix.py --manifest <run>/run-manifest.json plan
python scripts/run_agent_matrix.py --manifest <run>/run-manifest.json run \
  --stage-id calibration --provider-cap 1 --model-cap 1 --evaluation-cap 1
```

Use repeated `--cell task:model:configuration` arguments for a boot or
calibration subset. Omit them only after that subset proves the selected
provider/model/evaluator ceilings healthy.

## Provider identity and backup declarations

`provider` alone is not enough to identify an inference treatment. Each model
entry also records `provider_variant`, such as `serverless-standard` or
`on-demand-fast`. A candidate disclosure preserves that value.

A backup may be declared in the run manifest, but the coordinator never
activates it automatically:

```json
{
  "label": "Fireworks on-demand Fast",
  "provider": "fireworks",
  "provider_variant": "on-demand-fast",
  "model_id": "accounts/<account>/deployments/<deployment>",
  "wire_api": "responses",
  "adapter": "codex-cli-<version>",
  "status": "unqualified"
}
```

Changing provider, deployment, quantization, model revision, wire API, or
adapter creates a new disclosed cohort. It cannot fill holes in an existing
cohort without a documented deviation and new paid-run authorization. A
backup may be marked `qualified` only with durable qualification evidence in
the manifest.

## Fireworks on-demand

Fireworks on-demand deployments use dedicated GPUs and can be queried through
the same inference API as serverless models. They are the closest operational
backup for a Fireworks serverless cohort. Before qualification:

- prove that each exact benchmark model has an available deployment shape;
- record the deployment ID, base model, shape version, hardware, accelerator
  count, precision/quantization, region, and Responses API probe digest;
- warm the deployment outside a measured cell. A scale-from-zero 503 is a
  deployment preflight outcome, not a benchmark attempt;
- hold the chosen replica count for the cohort, then scale to zero or delete the
  deployment after final readback;
- approve a GPU-time ceiling. Fireworks bills active replicas by GPU-second,
  including idle time while a replica is running.

References: [deployment quickstart](https://docs.fireworks.ai/getting-started/ondemand-quickstart),
[autoscaling behavior](https://docs.fireworks.ai/deployments/autoscaling), and
[current pricing](https://fireworks.ai/pricing).

For an official comparison, either run the whole Fireworks cohort on the same
on-demand treatment or publish the on-demand rows as a separately labeled
cohort. Do not blend serverless and on-demand rows into one unlabeled score.

## DeepInfra

DeepInfra currently documents the exact model families used by the Fireworks
lane through its OpenAI-compatible Chat Completions endpoint:
[DeepSeek V4 Pro 0813](https://deepinfra.com/deepseek-ai/DeepSeek-V4-Pro-0813/api)
and [GLM 5.3 Flash](https://deepinfra.com/zai-org/GLM-5.3-Flash/api). The pinned
Codex CLI harness uses the Responses API, so DeepInfra is not a configuration
swap. It needs a versioned Chat Completions adapter and a separate qualification
cohort.

Qualification must prove tool calls, streaming completion, token accounting,
workspace edits, timeout handling, and transcript terminal semantics before
any scored run. Provider status is recorded as launch evidence, not treated as
a guarantee. See [DeepInfra status](https://status.deepinfra.com/).

## Recovery checklist

After a halted run:

1. prove no coordinator or workers remain;
2. hash the failed transcript, stderr, driver log, candidate directory, and
   report if present;
3. classify every cell as terminal, generated, untouched, or ambiguous;
4. evaluate generated cells without model access;
5. record the incident and exact approved retry scope;
6. resume untouched cells on the original treatment, or start a new explicitly
   labeled backup cohort;
7. rebuild aggregates once and scan all artifacts for secrets.

Quality failures are terminal and are never retried.
