# Python-to-Go campaign — execution disabled

Copy `run-manifest.template.json` into a new local run directory. It is intentionally
incomplete and cannot admit paid cells. Select releases/models/budgets, pin the
reviewed benchmark SHA, binaries, wheels, marketplace commit and evaluator image,
and populate stages using the existing v2 manifest contract. Preserve the exact
four task IDs and the two configurations. Qualification cannot fill missing pins.

Build `Dockerfile.go` only after selecting `GO_IMAGE` and `EVALUATOR_IMAGE` by digest.
The latter must be the reviewed ordinary benchmark evaluator image. The Go image
adds the compiler, the frozen module cache, bubblewrap and strace. Build for linux/amd64. It needs Linux
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
run the coordinator. No commands in this document were executed. No result JSON
or newer CLI/extension release version has been invented.
