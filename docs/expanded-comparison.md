# Expanded three-arm comparison

The first DeepSeek calibration covered one task and one scored attempt per arm.
It does not establish full-suite accuracy, confidence in accuracy parity, or that
strong models cannot fail the existing harder tasks. Qualify the corpus before
spending on a larger comparison; never weaken its independent oracle to improve
Sanka's results.

The new Flask fixtures and control candidates were authored with Codex for
evaluator qualification. They are not blind model attempts and must not appear
as model pass@1 results. The first three native references adapt existing private
benchmark controls; the wallet task adds an independent synthetic source.

## Freeze two lane manifests

Use the existing `sanka-bench/model-matrix-run-manifest/v2` format, one run directory
per lane. The coordinator now rejects an official manifest mixing destination
lanes. Keep the original eleven FastAPI tasks; add Flask 001–004 in the second
manifest. They share three source families, so do not pool them as fifteen
independent source applications or blend lane route-weighted scores.

Use `alone`, `sanka-cli`, `with-sanka` in that order and
`execution.sanka_workflow = "artifacts-first-v1"`. Both Sanka arms get the same
pinned CLI/extension and pre-generation treatment. Only `with-sanka` gets the
installed skill. Keep prompts, task inputs, model/provider version, generation
budget and concurrency identical within each paired comparison. Retain the
coordinator's rotated arm order. Record setup time separately and include it in
end-to-end time; a warm-cache comparison must be explicitly labeled.

The initial Flask extension converts a narrow stateless APIView subset. Its scan
and plan identify manual gaps on these harder sources. Zero native readiness is a
capability result, not a reason to omit the task, substitute a simpler source, or
mark a generated stub correct. Do not advertise FastAPI replay on the Flask arm;
use the supplied framework clients and task tests. A future converter improvement
is a new immutable treatment, never a rewrite of a frozen scored attempt.

## Model cohort

Select exact current model IDs and providers before authorizing paid execution:
include strong Chinese families (for example DeepSeek, Qwen, Kimi or GLM), an
additional open-weight family, and frontier proprietary models. These categories
overlap; classify by family and license rather than treating Chinese and open as
mutually exclusive. Model family names are selection criteria, not provider IDs.
Do not infer availability or prices from an old manifest.

Qualify each exact model/provider route on the same Claude Code harness before
expanding its matrix. Unsupported harness routes are an availability limitation,
not a 0% quality score. Pin the qualification evidence and model identity, and
obtain the total spending cap. The earlier one-task DeepSeek authorization does
not authorize every model and task here. Prepare manifests without credentials;
keep `paid_run_authorized` false until the chosen scope is authorized.

## Score and interpret

1. First report all scheduled task-level pass@1 outcomes, pending/infrastructure
   rows, paired accuracy regressions and per-lane route-weighted scores. Freeze
   failures; never generate a second candidate to replace a quality failure.
2. Report uncached input, cache reads/writes and output separately, alongside total
   tokens, observed model responses/tool calls, turns, retries and available actual
   provider cost. Unknown cost/calls stay unknown. Claude-equivalent prices are not
   actual third-party billing.
3. Compare generation, setup, evaluation and end-to-end time, plus successful tasks
   per wall-clock hour at the same concurrency. Serial time-derived throughput is
   an estimate, not measured concurrent throughput.
4. Inspect generated-artifact reuse and observed CLI/skill use. An available skill
   or a passing candidate alone does not establish that Sanka caused a gain.
5. Only claim efficiency at accuracy parity or better, with complete comparable
   evidence. Show per-model, per-task and per-lane results; do not hide expensive
   failures in averages of successful cases. Use more independent source families
   and repeated predeclared samples for stronger conclusions. Repeated samples
   estimate pass@1; selecting the best sample would change the metric.

The acceptance goal is non-decreasing paired accuracy with lower cost, tokens,
steps and end-to-end time. It is a hypothesis the benchmark tests, not a score the
harness guarantees. Add future difficulty through real behavioral requirements
and independently qualified edge cases, not through inspecting a model's hidden
answers or exposing the evaluator to an extension.

## Bounded paid pilot

An optional `execution.max_agent_cost_usd` is forwarded to Claude Code's
`--max-budget-usd`, pinned in each cell input digest and recorded in telemetry.
Its value uses the client's estimated price table; it is not a provider billing
limit. Exhaustion freezes the first candidate for scoring like a turn limit.
A run owner must separately reserve and track spending using the exact provider's
price card or billing evidence, account for in-flight work, and stop admission
when the remaining approved budget cannot cover another attempt. Never report
Claude-equivalent dollars as actual third-party spend.
