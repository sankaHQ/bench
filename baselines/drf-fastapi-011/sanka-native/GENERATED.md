# Sanka native-converter provenance (drf-fastapi-011)

Generated once with published PyPI `sanka-cli` 0.1.8 delegating to
`sanka-migrate` 0.1.0a10, installed inside the fixture-capable virtualenv with
Python 3.12.13, Django 5.2.17, Django REST Framework 3.18.0, and FastAPI
0.141.1.

The unattended pass@1 run was executed from
`<repo>/tasks/drf-fastapi/drf-fastapi-011/source`:

```bash
sanka scan . --artifact-dir <local-path> --json --no-color
sanka plan . --to fastapi --strategy native --generation minimal \
  --package-manager uv --output <local-path> --artifact-dir <local-path> \
  --json --no-color
sanka apply --root . --artifact-dir <local-path> --output <local-path> \
  --plan-hash sha256:78006157c9b01dfb6fd00b64463ed4c9d3bbbe3f43dcaad0880dceb42eba1ed1 --bench-candidate <local-path> \
  --json --no-color
```

Scan reported 5 endpoints and scan hash `sha256:9f3813da82fbe8e94dc3ce067e220468b73e9d69c614fa1a247ba802d69afd08`. The
native plan hash is `sha256:78006157c9b01dfb6fd00b64463ed4c9d3bbbe3f43dcaad0880dceb42eba1ed1` with readiness
0%: 0 of 5
non-alias routes generatable and 5 requiring adaptation.
Adaptation codes: `SANKA_DRF_SERIALIZER_SEMANTICS_UNSUPPORTED`, `SANKA_DRF_VIEW_KIND_UNSUPPORTED`.

The raw engine artifact is preserved locally with digest `sha256:5002a2fc012b178838240d5a6b0e9999cad4fc7d7d6967885ab4038e8441d090`. The
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
