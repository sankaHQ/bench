# Sanka Migration Bench

Sanka Bench tests whether a repository migration preserves behavior and uses the
target framework. The source application defines the expected behavior. The
evaluator checks HTTP responses, database changes, side effects and native
request handling against a frozen candidate.

The suite contains 17 tasks: 11 Django REST Framework to FastAPI migrations and
6 DRF to Flask migrations. Both targets retain the Django ORM and database schema.
The default agent is the Sanka native harness. It controls model calls, sandboxed
tools and the Sanka workflow; the evaluator grades every configuration independently.

[Published results](https://sanka.com/bench) ·
[Native harness](docs/native-harness.md) ·
[Run manifests and recovery](docs/measurement-runs.md) ·
[Task details](docs/task-catalog.md)

## Start with one local evaluation

Use Python 3.12 and [uv](https://docs.astral.sh/uv/). Docker or Podman is needed
for container evaluation. Agent generation also requires macOS `sandbox-exec`
or Linux `bubblewrap`; missing isolation stops the run.

```bash
git clone https://github.com/sankaHQ/bench.git
cd bench
uv sync --frozen --python 3.12 --extra fixture --group dev
uv run sanka-bench validate

uv run sanka-bench evaluate \
  --runner local \
  --task tasks/drf-fastapi/drf-fastapi-001 \
  --candidate baselines/drf-fastapi-001/native-reference \
  --output reports/first-evaluation.json
```

This evaluates a saved reference candidate. It does not call a model or incur
inference charges. Omit `--runner local` to use the default Docker runner, which
disables network access during evaluation.

## What to compare

The standard comparison is Model Only versus Model + Sanka CLI. Skills remain an
optional third configuration for experiments.

| Manifest configuration | What the model receives |
| --- | --- |
| `alone` | Task contract and sandboxed `exec`/`read` tools |
| `sanka-cli` | The same task, generated Sanka artifacts and public verification |
| `with-sanka` | The CLI treatment plus the pinned Sanka Skill |

`with-sanka` is the historical identifier for the Skills treatment in native
candidate IDs and matrix manifests. Use `sanka-cli` for CLI-only runs.

The native controller runs this preparation for Sanka treatments:

```text
sanka scan -> sanka plan -> sanka apply -> sanka test -> sanka verify
```

If public verification succeeds without warnings, generation ends. Otherwise,
the model receives the lifecycle results and can repair the candidate. Public
verification is not the benchmark score: the independent evaluator still grades
the frozen output, including scenarios hidden from the model.

Keep the model, effort, task set, limits and grading contract fixed across
configurations. A CLI improvement must show up in the measurements; it never
changes the passing criteria.

## Run a model candidate

Direct API routes support OpenAI Responses, Fireworks Chat Completions and
Anthropic Messages. Set only the provider credential needed for the run:
`OPENAI_API_KEY`, `FIREWORKS_API_KEY` or `ANTHROPIC_API_KEY`. Keep credentials
outside committed files and retained artifacts.

This example makes paid API calls. Set `MODEL_ID` to the exact model you intend
to test and use a new output directory:

```bash
export MODEL_ID="your-exact-model-id"
RUN_DIR="$(pwd)/runs/my-first-run"

uv run python scripts/run_agent_candidate.py \
  --agent sanka-native --provider openai --billing-mode api_key \
  --model "$MODEL_ID" --reasoning-effort high \
  --task tasks/drf-fastapi/drf-fastapi-001 \
  --candidate-id sanka-native-model-alone \
  --out "$RUN_DIR/candidate" --sandbox "$RUN_DIR/sandbox" \
  --max-turns 60 --wall-clock-seconds 900
```

Generation and grading are separate. Evaluate the frozen `candidate.yaml` after
generation using the same task and evaluator as the reference example.

For CLI-only candidates, use an ID ending in `-sanka-cli` and pass
`--sanka-bin` with the pinned executable. `requirements-sanka.txt` currently pins
`sanka-cli==0.2.7`. Create its environment separately from the evaluator:

```bash
make sanka-toolchain RUN_DIR="$RUN_DIR"
export SANKA_BIN="$RUN_DIR/toolchain/bin/sanka"
```

This installs the CLI only. Install the separately pinned extension wheels and
prepare the run's isolated Sanka home before generation. The
[native harness setup](docs/native-harness.md#running) explains executable,
extension, qualification and manifest pins, plus output/context limits and
estimated-cost caps. The Anthropic adapter requires adaptive thinking and
`output_config.effort` support.

Explicit `--agent claude-code` and `--agent codex` adapters remain available for
reproducing historical runs. Do not relabel their results as native-harness runs.

### Subscription access

Subscription access is experimental and unofficial: DWYOR (use at your own risk).
It delegates authentication and inference to the provider's installed CLI, not
a provider-approved subscription API. Direct API and managed subscription runs
have different context handling; record which transport produced each result.

```bash
# Requires the official Codex CLI.
uv run sanka-bench login --provider chatgpt --device-auth
uv run sanka-bench login status --provider chatgpt

# Requires the official Claude Code CLI.
uv run sanka-bench login --provider claude
uv run sanka-bench login status --provider claude
```

For generation, select `--provider openai` or `--provider anthropic` with
`--billing-mode subscription`. Bench serializes cells per subscription account.
Authentication or quota errors stop admission; they do not trigger API billing.
Use `uv run sanka-bench logout --provider chatgpt` or `--provider claude` to sign out.
See [provider login](docs/provider-login.md) for credential locations, locks,
refresh ownership, account boundaries and usage accounting.

## Run a reproducible matrix

Before a paid campaign, qualify the exact provider/model route and freeze a v2
manifest. It records task and toolchain revisions, model identity, reasoning
effort, configuration, prices, budgets, concurrency and qualification hashes.
New native runs use `execution.sanka_workflow: native-lifecycle-v1`.

Use one coordinator for the campaign:

```bash
uv run python scripts/run_agent_matrix.py --manifest "$RUN_DIR/run-manifest.json" plan
uv run python scripts/run_agent_matrix.py --manifest "$RUN_DIR/run-manifest.json" run --stage-id "$STAGE_ID"
uv run python scripts/run_agent_matrix.py --manifest "$RUN_DIR/run-manifest.json" report
```

`STAGE_ID` must name a stage in that manifest. `plan` and `report` do not generate
new candidates. `run` admits cells within the configured budgets and concurrency.
Keep each campaign's workspaces and artifacts separate. Subscription cells remain
serialized even when API providers run alongside them.

Preserve completed candidates when resuming. Fix evaluator or infrastructure
problems without generating replacement model answers where the saved candidate
can be regraded. Keep model failures as results. A new model attempt or changed
toolchain needs new evidence; do not overwrite an earlier pass@1 attempt.

See [measurement runs](docs/measurement-runs.md) for the manifest schema,
qualification, isolation, resume rules and failure accounting, and
[expanded comparisons](docs/expanded-comparison.md) for experiment design.

## Read the results

A task is fully migrated only when every hard gate passes:

| Gate | What it checks |
| --- | --- |
| Source qualified | The original application is a valid behavior oracle |
| Regression tests | Existing tests still pass |
| Target boot | The candidate starts successfully |
| Native target | Requests run through the declared target framework |
| HTTP parity | Responses match the source contract |
| Database parity | Database changes match |
| Side-effect parity | Observable effects, including stored files, match |
| Determinism | Results repeat across clean runs |

A compatibility bridge that dispatches back into DRF fails native-target
compliance even if its responses match. Passing 31 of 32 scenarios does not pass
the task. Scenario percentages help diagnose the failure; they do not offset a
failed gate.

Task pass@1 counts fully migrated tasks on their first scored attempt. Reports
also support route-weighted scores: a task contributes its method-routes only
when the entire task passes. State the denominator and task coverage when
comparing results. Keep route-weighted scores separate by migration lane.

Read accuracy alongside input/output tokens, cache usage, tool calls, retries,
setup time, generation time, grading time and end-to-end time. Queue elapsed time
is a separate measure of parallel throughput. Cost uses reported usage and saved
pricing; API-equivalent estimates for subscriptions are not invoices. Missing
usage stays missing rather than being extrapolated.

Published results must trace back to frozen candidates, reports and agent logs.
A view that substitutes later task reruns is a latest-results summary, not a new
full-suite pass@1 experiment. See [measurement design](docs/measurement-design.md).

To render saved evaluator reports without model calls:

```bash
make report
# Writes reports/index.html and reports/summary.svg.
```

## Tasks and controls

The 17 tasks use 14 source applications. The first three Flask tasks reuse source
families from FastAPI tasks 010, 009 and 011; the other Flask tasks add independent
applications. The [task catalog](docs/task-catalog.md) describes their contracts.

| Directory | Contents |
| --- | --- |
| `tasks/drf-fastapi/` | 11 tasks covering validation, auth, nested writes, signals, pagination, uploads and other behaviors |
| `tasks/drf-flask/` | 6 tasks covering orders, uploads, aggregates, wallets, conditional documents and reservations |
| `baselines/` | Saved positive and negative controls, plus converter output where provided |
| `src/sanka_bench/` | Evaluator, native harness, accounting and report code |
| `scripts/` | Candidate runners, matrix coordination and route qualification |
| `src/sanka_bench/schema/` | Task, candidate and result schemas |
| `tests/` | Harness tests and evaluator regression tests |

No-op and compatibility-bridge controls must fail the relevant gates. Native
references must pass. Frozen Sanka converter baselines record what that pinned
release generated; they are not a substitute for measured agent candidates.
Do not commit campaign transcripts or credentials as baselines.

## Development checks

```bash
make test-unit                  # Harness feedback without evaluator suites
make test-evaluator-008         # One FastAPI task's evaluator tests
make test-evaluator-flask-002   # One Flask task's evaluator tests
make check TEST_WORKERS=1       # Lint, typing, tests and task validation
make baselines                 # Local baseline evaluations
make docker-baselines          # Container baseline evaluations
```

`make check` defaults to two task workers. Keep local concurrency bounded; use
one worker when memory is constrained. CI also runs Docker baselines.

Before releasing a converter change, run the manual regression workflow against
its exact extension commit:

```bash
gh workflow run converter-regression.yml --repo sankaHQ/bench --ref main \
  -f extensions_sha=FULL_40_CHARACTER_COMMIT_SHA
```

See the [converter regression instructions](https://github.com/sankaHQ/extensions/blob/main/docs/converter-regression.md).
This workflow is a release check, not automatic coverage on extension PRs.

## Contributing

This repository owns the evaluator, fixtures, isolation and reports.
[sankaHQ/sanka](https://github.com/sankaHQ/sanka) owns the migration runtime;
[sankaHQ/extensions](https://github.com/sankaHQ/extensions) owns extensions.
All candidates use the same evaluator contract.

Propose a task with a source application, the behaviors it must preserve and the
failure mode existing tasks miss. Include scenarios, evaluation configuration and
positive/negative controls. Hidden grading scenarios must stay outside the
candidate-visible workspace. See [design](docs/design.md) for evaluator details.

## License

Apache-2.0. Third-party fixtures and baseline outputs retain their own license
and provenance disclosures.
