# Sanka native-converter provenance (drf-fastapi-010)

Generated once with published PyPI `sanka-cli` 0.1.8 delegating to
`sanka-migrate` 0.1.0a10, installed inside the fixture-capable virtualenv with
Python 3.12.13, Django 5.2.17, Django REST Framework 3.18.0, and FastAPI
0.141.1.

The unattended pass@1 run was executed from
`<repo>/tasks/drf-fastapi/drf-fastapi-010/source`:

```bash
sanka scan . --artifact-dir <local-path> --json --no-color
sanka plan . --to fastapi --strategy native --generation minimal \
  --package-manager uv --output <local-path> --artifact-dir <local-path> \
  --json --no-color
sanka apply --root . --artifact-dir <local-path> --output <local-path> \
  --plan-hash sha256:b7a431f75e95d3e0200e1ccb2049ed06a277432f1fbf794522fd825bee251f31 --bench-candidate <local-path> \
  --json --no-color
```

Scan reported 5 endpoints and scan hash `sha256:c27dae3995b75dd03d9e5082d5cc4414f15a1ba97227934afd0d5f7c28b67192`. The
native plan hash is `sha256:b7a431f75e95d3e0200e1ccb2049ed06a277432f1fbf794522fd825bee251f31` with readiness
0%: 0 of 5
non-alias routes generatable and 5 requiring adaptation.
Adaptation codes: `SANKA_DRF_CUSTOM_ACTION_UNSUPPORTED`, `SANKA_DRF_VIEWSET_OVERRIDES_UNSUPPORTED`.

The raw engine artifact is preserved locally with digest `sha256:d6f5c0d1db288ee41fa878c11edb2f86f0004129c2a643af5c2ecef541c28404`. The
committed copy changes only machine-local absolute path strings to `<repo>` or
`<local-path>`; generated application code and behavioral content are otherwise
untouched.

## Honest outcome: readiness-aware abstention

Apply returned `SANKA_READINESS` with `the native plan contains no generatable routes` under the default
50% readiness threshold. The engine emitted `GAP-REPORT.md`,
`gap-report.json`, and `plan-fastapi.json` instead of a scaffold. Benchmark
packaging adds only the required noop `candidate.yaml`; no overlay exists.
Nothing was retried or hand-fixed.

## Evaluator outcome

Local and network-disabled Docker evaluation have identical gates and metrics.
Source qualification and regression pass; target boot fails, and behavior,
database, side-effect, route, and native-serving comparisons are 0/32.
