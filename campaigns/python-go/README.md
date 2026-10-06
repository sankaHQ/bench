# Python-to-Go campaign — execution disabled

Copy `run-manifest.template.json` into a new local run directory. It is intentionally
incomplete and cannot admit paid cells. CLI **0.3.9** and Python-to-Go extension
**0.1.0a17** are selected. Select models/budgets, pin the
reviewed benchmark SHA, binaries, local wheel paths and evaluator image,
and populate stages using the existing v2 manifest contract. Preserve the exact
four task IDs and the two configurations. Qualification cannot fill missing pins.

## Selected releases

The [release lock](../../src/sanka_bench/python_go_release.json) records verified
download URLs and SHA256 hashes. Go a17 means
[api-converters-v0.1.0a17](https://github.com/sankaHQ/extensions/releases/tag/api-converters-v0.1.0a17),
at marketplace commit `191bdaf9a92f567e74ac0af0b253b99e99158a4c`.
Its five extension wheels are Python-to-Go a17, extension SDK a4, connector SDK a12,
code migration a4, and HTTP replay a2. The sixth wheel is CLI 0.3.9 from PyPI.
All six wheel payloads were downloaded and hash-checked without installing or running them.
The released Fiber/SQLite go.mod and go.sum match this repository byte for byte.

For the future run, create a separate CLI environment using Python 3.12 and the
pinned CLI wheel. Resolve and archive its transitive Python dependency lock for
the chosen host. Do not use `make sanka-toolchain`: that preserves CLI 0.2.7 for
historical campaigns. Put all six absolute wheel paths and their hashes into
`toolchain.wheel_hashes`; the run rejects missing or changed release artifacts.

CLI 0.3.9 installs extension wheels into its own sealed environment during
`extension add`. They do not need to be installed into the CLI environment.
Preflight checks the installed CLI payload; each candidate setup checks the
extension's version, marketplace commit and manifest digest returned by the CLI.
The CLI verifies wheel hashes and seals the cached runtime before executing it.
Use a separate Python 3.12 benchmark environment from the frozen `uv.lock` for
source replay (`SANKA_GO_SOURCE_PYTHON`); do not inherit the old evaluator's
PYTHONPATH into the CLI. Record both Python patch versions and dependency locks.

## Deferred qualification

Build `Dockerfile.go` only after selecting `GO_IMAGE` and `EVALUATOR_IMAGE` by digest.
The latter must be the reviewed ordinary benchmark evaluator image. The Go image
adds the compiler, the frozen module cache, bubblewrap and strace. Build for the pinned linux/amd64 or linux/arm64 platform. It needs Linux
user namespaces; failure to create a serving sandbox stops evaluation.
The Docker invocation relaxes the outer seccomp/AppArmor profiles only for this
lane so nested bubblewrap namespaces can be created; the offline, read-only outer
container and empty inner serving sandbox remain required. Do not use this image
until controls qualify on the intended host/container engine.

Qualification is a separate future execution step, not a paid model campaign:

```bash
PYTHONPATH=src python scripts/qualify_python_go.py --execute \
  --manifest /absolute/run/run-manifest.json --output /absolute/run/qualification
```

It executes four tasks × five controls, with each scenario repeated twice. The
positive reference is independently authored and **unqualified**. Negative copies
attempt Python delegation, discard writes, forge probe stdout and exit early, or
retain the unchanged Python source.
No result is assumed. Preserve failed reports and fix the evaluator/reference
before any scored campaign. Record the emitted qualification JSON path and SHA256
in the manifest; qualification must match the exact benchmark SHA and Go pins.

The native harness runs Scan/Plan/Apply/Test/Verify before promoting generated Go
files. Those extension checks are advisory, not the benchmark verdict. Since the
Go extension verifier is not the DRF candidate verifier, Go runs finish as
`completed_unverified` and the independent evaluator owns the score. Both arms
get the same public factory contract, frozen go.mod/go.sum and grading criteria. The CLI arm includes
a small adapter from generated `OpenSQLite`/`NewApp` to `NewBenchApp`.

A separate user authorization is required to set paid-run authorization true and
run the coordinator. No qualification or benchmark commands in this document
were executed. No scores or qualification results have been created.

## Native local Podman and agent-only runs

Set `go_toolchain.platform` to `linux/arm64` for a native Apple Silicon Podman VM,
or `linux/amd64` for x86 Linux. Use that same platform for both image builds and
qualification. Emulated amd64 tracing under Rosetta is not sufficient. Both
architectures require the exact trusted syscall address and the same full
control matrix; there is no weaker native gate. Requalify whenever platform,
image or benchmark revision changes.

`execution.configurations: ["alone"]` runs agent-only cells without requiring
Sanka wheel or CLI pins. The Go compiler/image and qualification pins remain
mandatory. Keep later CLI comparisons in a separately authorized cohort.
