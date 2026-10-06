# Python-to-Go benchmark implementation and deferred run plan

Updated 2026-10-06 for CLI 0.3.9 and Python-to-Go extension 0.1.0a17,
with authorization to prepare **without running the benchmark**.

## Implemented locally

- Four task v0.3 manifests reuse pinned DRF fixtures and all 82 full scenarios;
  33 scenarios are public to candidates. Historical 17-task trees and results
  remain unchanged. See [task contracts](../../../tasks/python-go/README.md).
- Go/Fiber/SQLite schema, build and serving driver, independent state comparisons,
  bounded process cleanup and a Linux/amd64 sandboxed test-client probe.
- Native harness extension selection, Go lifecycle, artifact promotion and public
  adapter. Test/Verify from the extension are advisory; independent grading owns
  the verdict. Generation ends completed_unverified until that grading occurs.
- Equal dependency locks in both arms, exact four-task admission, CLI/extension/SDK
  wheel hashes, installed CLI payload checks, exact cached-extension lock readback,
  immutable marketplace revision and image/SHA qualification.
- Independently authored native reference, negative controls and an explicitly
  invoked qualification script. No positive outcome has been assumed.
- Incomplete [campaign template](../../../campaigns/python-go/run-manifest.template.json),
  with authorization false, no models, and verified selected release pins.
- Separate sanka-public preview: Python → Go — Not run, with historical versions
  and the existing Flask upload-rerun exception. It adds no result rows or scores.

The evaluator uses Fiber App.Test and separately compiles cmd/api; this proves
neither TCP listener operation nor production migration readiness. The native
witness observes the trusted probe, with candidate stdout forgery as a negative
control. It is not a hostile-native-code security boundary. Target regression
means successful compilation; scenario parity supplies the behavioral checks.

## Still required before execution

1. Review and land the final source, then freeze the reviewed benchmark commit.
   Static and mocked preparation checks are separate from runtime qualification.
2. Use the selected [release lock](../../../src/sanka_bench/python_go_release.json):
   CLI 0.3.9, Python-to-Go a17 from api-converters-v0.1.0a17, extension SDK a4,
   connector SDK a12, code migration a4 and HTTP replay a2. Downloaded wheel
   hashes, marketplace manifest, lifecycle configuration and generated adapter
   signatures were inspected. Record host wheel paths, harness binaries, Python
   3.12 patch versions and resolved dependency locks. Follow the campaign guide
   for separate CLI/source environments. Keep historical requirements-sanka.txt
   (CLI 0.2.7) unchanged.
3. Build the dedicated Linux/amd64 evaluator with digest-pinned GO_IMAGE and
   EVALUATOR_IMAGE and the exact BENCH_SHA label. Freeze its resulting digest.
   User namespaces and external syscall tracing must work on the selected engine.
4. Explicitly authorize and run the unscored qualification described in the
   [campaign guide](../../../campaigns/python-go/README.md): four tasks × five
   controls. Each scenario repeats twice. Native must pass all eight gates;
   Python delegation and stdout forgery must fail native grading; missing writes
   must fail database parity; unchanged Python must fail native grading. Preserve
   all reports. Admission checks their hashes and complete control coverage.
5. Select exact provider/model IDs, reasoning effort, equal turn/time/token/cost
   budgets and spending cap. Use the historical roster where available; disclose
   any changed roster. Complete the existing v2 stages and route requirements.
6. Obtain execution authorization with that concrete scope. Keep authorization
   false until then. Run only python-go-001 through python-go-004, configurations
   alone and sanka-cli, one attempt each. For N models this is **8N scored cells**,
   plus separately recorded qualification. Never run a wildcard/all-task command.
7. Follow the existing benchmark skill's provider qualification, bounded
   calibration, sequential CLI boot gate and single-coordinator execution rules.
   Freeze candidates and failures; infrastructure regrading uses those same bytes.
8. Review all eight gates, coverage, actual versions, timing, usage, missing usage,
   cost basis and cohort status. Changed tools require a new cohort/run ID.

## Historical provenance and publication

The original inspected bench base is 10860b35a6cf008bad331e33e75e56aa93f7439f.
Destination dependency locks came from extensions commit
10fb419e67b9f524406d999d4e3883494c3be8ce and match the selected a17 release
wheel byte for byte. The selected marketplace commit is
191bdaf9a92f567e74ac0af0b253b99e99158a4c.
The historical September 12 results record CLI 0.2.7 and extensions 0.1.0a16,
except eight drf-flask-002 CLI upload reruns at unreleased extension commit
c1d60b4b4bd26778dd56e85331e4a5cedfbd03a6. Preserve that exception.

The prepared website copy shows Not run across all benchmark views. After an
actual reviewed campaign, add a distinct Python → Go* cohort with its own four-task
denominator, date, exact versions, model coverage and evidence links. Implement
cohort-specific data and aggregation checks then; never put Go cells into old
allRows/allCells/fullPairs or treat absent cells as zero scores. Old denominators
remain 17. No result snapshot or new aggregation was created in this change.

Post-run disclosure template:

> * Python → Go was measured separately on {date}, using Sanka CLI {version} and
> sanka-extension-python-to-golang {version} ({commit}). Other results retain
> Sanka CLI 0.2.7 and extensions 0.1.0a16, with the disclosed c1d60b4 upload-task
> exception. Those tasks were not rerun. Cohort scores are not a controlled
> comparison of old versus new Sanka versions.

Exact-head PR approval and separate production deployment authorization remain
required before publication. Local implementation is not a published benchmark.

## Validation boundary

Preparation uses static provenance/schema, syntax, lint and type checks plus
focused pure or mocked unit tests. No source/target applications, migrations,
Go compilation, container builds, qualification controls or model calls were
launched. The four tasks and reference implementation remain **unqualified**.

The initial PR's ordinary GitHub CI passed the 17 historical local and Docker
fixture shards; its unit job failed because a mocked Docker fixture omitted
task.yaml. That fixture is corrected without invoking Docker locally. Static
review also found and fixed the old assumption that the extension is installed
inside the CLI environment: CLI 0.3.9 owns a separate sealed extension runtime.
The preflight now checks the CLI payload and each candidate setup validates the
exact released extension lock. No historical scored results were rerun or changed.

Focused preparation checks cover task schemas and copied scenarios, campaign
execution holds, native witness rejection, generated-file promotion, release
lock matching, mocked Docker calls, and mocked Go lifecycle ordering. Published
release files were downloaded and inspected, without installation or execution.
The website remains a separate draft PR; no page has been deployed here.

Latest preparation validation: 42 focused pure/mocked tests passed; all 21 task
manifests, 64 candidate definitions and three schemas validated; provenance,
repository Ruff lint/format and focused go_lane mypy passed. Independent static
review reported no additional actionable findings. These checks do not qualify
the runtime or establish migration quality.
