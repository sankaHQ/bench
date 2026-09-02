# Sanka native-converter provenance (drf-fastapi-005)

Generated once with published PyPI `sanka-cli` 0.1.8 delegating to
`sanka-migrate` 0.1.0a10, installed inside the fixture-capable virtualenv with
Python 3.12.13, Django 5.2.17, Django REST Framework 3.18.0, and FastAPI
0.141.1.

The unattended pass@1 run was executed from
`<repo>/tasks/drf-fastapi/drf-fastapi-005/source`:

```bash
sanka scan . --artifact-dir <local-path> --json --no-color
sanka plan . --to fastapi --strategy native --generation minimal \
  --package-manager uv --output <local-path> --artifact-dir <local-path> \
  --json --no-color
sanka apply --root . --artifact-dir <local-path> --output <local-path> \
  --plan-hash sha256:09e0249c005628c35677d7073663f7df0d47df87bb82144443233bbc5c6a4f0b --bench-candidate <local-path> \
  --json --no-color
```

Scan reported 16 endpoints and scan hash `sha256:38076cbbdeef1e53814dcc3cdca8dec68f8c9a33c772ff2635624a21407f89d2`. The
native plan hash is `sha256:09e0249c005628c35677d7073663f7df0d47df87bb82144443233bbc5c6a4f0b` with readiness
12.5%: 1 of 8
non-alias routes generatable and 7 requiring adaptation.
Adaptation codes: `SANKA_DRF_AUTH_PERMISSIONS_UNSUPPORTED`, `SANKA_DRF_CUSTOM_ACTION_UNSUPPORTED`.

The raw engine artifact is preserved locally with digest `sha256:314a9103734cd6ad3204af9790258d3a8f815900cab109de38048ec2ba75f77e`. The
committed copy changes only machine-local absolute path strings to `<repo>` or
`<local-path>`; generated application code and behavioral content are otherwise
untouched.

## Honest outcome: readiness-aware abstention

Apply returned `SANKA_READINESS` with `readiness is below --min-readiness 50%` under the default
50% readiness threshold. The engine emitted `GAP-REPORT.md`,
`gap-report.json`, and `plan-fastapi.json` instead of a scaffold. Benchmark
packaging adds only the required noop `candidate.yaml`; no overlay exists.
Nothing was retried or hand-fixed.

## Evaluator outcome

Local and network-disabled Docker evaluation have identical gates and metrics.
Source qualification and regression pass; target boot fails, and behavior,
database, side-effect, route, and native-serving comparisons are 0/31.
