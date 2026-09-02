# Measurement design: samples, intervals, and cost per verified route

This document specifies how the bench turns cell outcomes into numbers that can carry a
claim. With one sample per cell and all-or-nothing route weights, a single hidden
scenario moves 14–36 of 170 routes, so a six-model delta of two points sits inside the
noise of three such flips. SWE-bench gets stable numbers from many
instances, not from a cleverer score; this design adds instances (samples and tasks) and
reports the uncertainty that remains.

## Cell identity with samples

A cell is `(task, model, config, sample)`. The manifest declares
`execution.samples` (default `1`; published deltas require `3`). Sample indices are
`1..samples`. Cell artifacts and result files carry the sample in the candidate id:

```
<task>-<candidate_slug>-<config>-s<k>      e.g. drf-fastapi-005-claude-opus-with-sanka-s2
```

Every sample is an independent unattended attempt under the same budget and prompt; no
sample is retried into shape, and the first sample is not privileged. `family_key()`
strips the task prefix and the `-s<k>` suffix, so the report groups all samples of one
`(model, config)` together while keeping every result file addressable.

## Aggregates per (model, config)

For each family the report computes, over the tasks it covers:

| Field | Definition |
| --- | --- |
| `samples` | samples per task (uniform within a run; recorded per task otherwise) |
| `pass_rate` | passed task-samples ÷ all task-samples, with a 95 % Wilson interval |
| `score` | mean over samples of the route-weighted Migration Quality Score v0.2 (routes of passed tasks ÷ suite routes), with a 95 % percentile-bootstrap interval (2 000 resamples of tasks with replacement, each resample averaging that task's sample outcomes) |
| `verified_routes` | mean over samples of routes verified |
| `cost_usd`, `duration_seconds` | summed over all task-samples and reported per sample (÷ samples) so runs of different `samples` compare |
| `cost_per_verified_route` | `cost_usd ÷ verified_routes` per sample, mean over samples; `null` when cost is pending |
| `scenario_parity` | Migration Quality Score v0.3 companion: passed ÷ total hidden scenarios for behavior, database, side-effect, and native compliance, pooled over task-samples |

Wilson intervals answer "how many task-samples passed"; they treat every task as one
trial regardless of size. The bootstrap interval answers "how much route-weighted score
would move if the task list were drawn again"; it carries the weights. Both are shown; a
published delta between two families must be supported by the bootstrap intervals of
the two route-weighted scores not overlapping, or by a paired bootstrap over tasks of the
per-task score difference whose interval excludes zero. Pass rate and its Wilson interval
are reported beside the score, never instead of it.

## Suite size

Thirty or more tasks before any published matrix. Synthetic variants of the eleven
existing tasks cover the failure families the notes and the verifier target; Verified-tier
real repositories join the suite starting with the smallest scannable ones
(djangoforapis, styleguide-example, kitsune), each with a recorded scan, public scenarios
sampled from the hidden superset, and a source-oracle driver. Real-repository tasks carry
their license and commit in `task.yaml`. "Hidden" means hidden from the agent: the
harness copies only `public-tests/` into the workspace, while the evaluator grades the
superset named by `evaluation.scenarios` (`evaluation/scenarios.json` on the tasks that
have one). Those files are tracked in this repository today; if the repository is
public, move them to a private companion the coordinator mounts at evaluation time
before publishing a matrix.

## Publication rules

- Every published number comes from an executed run whose manifest names the samples,
  providers, prices, and authorization; pending provider readbacks are shown as pending.
- Lead with cost per verified route beside the score. State plainly which families the
  tool changed and which it did not.
- The all-or-nothing score stays the headline; scenario parity is the continuous
  companion and is labelled v0.3 until it has its own contract.
- Confidence intervals are printed with the numbers they qualify; a delta without an
  interval is not published.

## Implementation map

- `scripts/run_agent_matrix.py`: `execution.samples` in the manifest; `CellSpec.sample`;
  candidate ids with `-s<k>`; expected rows = tasks × models × configs × samples.
- `src/sanka_bench/report.py`: `family_key()` strips the sample suffix; `collect()` groups
  task-samples; new `statistics.py` provides `wilson_interval()`,
  `bootstrap_interval()`, and the paired difference; rows gain the fields above; the HTML
  and SVG renderers print intervals next to means.
- `tests/`: unit tests for the interval functions against known values, a synthetic
  three-sample report fixture, and a rendering test that pins the interval columns.
