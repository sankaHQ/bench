# Sanka native-converter provenance (drf-fastapi-009)

Generated once with published PyPI `sanka-cli` 0.1.8 delegating to
`sanka-migrate` 0.1.0a10, installed inside the fixture-capable virtualenv with
Python 3.12.13, Django 5.2.17, Django REST Framework 3.18.0, and FastAPI
0.141.1.

The unattended pass@1 run was executed from
`<repo>/tasks/drf-fastapi/drf-fastapi-009/source`:

```bash
sanka scan . --artifact-dir <local-path> --json --no-color
sanka plan . --to fastapi --strategy native --generation minimal \
  --package-manager uv --output <local-path> --artifact-dir <local-path> \
  --json --no-color
sanka apply --root . --artifact-dir <local-path> --output <local-path> \
  --plan-hash sha256:bb7db721438ae43fb9dae350001b69091ea2a28426f23db89c20c699b7b239fe --bench-candidate <local-path> \
  --json --no-color
```

Scan reported 12 endpoints and scan hash `sha256:e11664285f3dae1f91b46c9575cdef0d53270b825387366fae27f00fc0f3bafd`. The
native plan hash is `sha256:bb7db721438ae43fb9dae350001b69091ea2a28426f23db89c20c699b7b239fe` with readiness
0%: 0 of 12
non-alias routes generatable and 12 requiring adaptation.
Adaptation codes: `SANKA_DRF_CUSTOM_ACTION_UNSUPPORTED`, `SANKA_DRF_SERIALIZER_SEMANTICS_UNSUPPORTED`.

The raw engine artifact is preserved locally with digest `sha256:9702b51849a60d42ea0e7d00df09de2262e8f1437cc4da99c5e0eb3fc4b68607`. The
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
