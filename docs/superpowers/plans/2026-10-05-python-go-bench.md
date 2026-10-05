# Python-to-Go benchmark implementation and deferred run plan

Updated 2026-10-05 after authorization to implement **without running**.

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
  wheel payload checks, immutable marketplace revision and image/SHA qualification.
- Independently authored native reference, negative controls and an explicitly
  invoked qualification script. No positive outcome has been assumed.
- Incomplete [campaign template](../../../campaigns/python-go/run-manifest.template.json),
  with authorization false and no models or invented Sanka release pins.
- Separate sanka-public preview: Python → Go — Not run, with historical versions
  and the existing Flask upload-rerun exception. It adds no result rows or scores.

The evaluator uses Fiber App.Test and separately compiles cmd/api; this proves
neither TCP listener operation nor production migration readiness. The native
witness observes the trusted probe, with candidate stdout forgery as a negative
control. It is not a hostile-native-code security boundary. Target regression
means successful compilation; scenario parity supplies the behavioral checks.

## Still required before execution

1. Review and land the final source. Complete ordinary focused/CI runtime checks
   when authorized; none ran during this implementation. Fix any findings without
   weakening scenarios, then freeze the reviewed benchmark commit.
2. Select newer immutable Sanka CLI, Python-to-Go extension and SDK wheels. Record
   versions, wheel hashes, marketplace commit, harness binaries and Python locks.
   Keep historical requirements-sanka.txt (CLI 0.2.7) unchanged. Confirm the release
   still implements the inspected Scan/Plan/Apply/Test/Verify and artifact contract.
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
10fb419e67b9f524406d999d4e3883494c3be8ce; that is **not** a selected Sanka release.
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

Only static provenance/schema, syntax, lint, type and design checks are permitted
for this implementation request. Written runtime tests, reference controls, Go
builds, containers, source/target apps, migrations and model calls remain unrun.
Do not report qualification, test execution or operational readiness as passed.

Static checks completed: provenance and scenario copies verified; schema validation
accepted 21 tasks, 64 candidate definitions and three schemas; repository Ruff
format/lint and focused mypy (eight changed source files) passed; Python AST and
Go/gofmt syntax passed. Historical task/result/toolchain files have no diff.
The public page's design-token check passed. Full mypy could not complete because
the existing environment lacks Flask/Werkzeug; TSX compilation was unavailable
because TypeScript is absent. No dependencies were installed to bypass that hold.
Runtime tests, Go compilation, container builds and browser checks remain pending.
