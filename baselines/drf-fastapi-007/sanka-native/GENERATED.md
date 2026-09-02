# Sanka native-converter provenance (drf-fastapi-007)

Generated once with published PyPI `sanka-cli` 0.1.8 delegating to
`sanka-migrate` 0.1.0a10, installed inside the fixture-capable virtualenv with
Python 3.12.13, Django 5.2.17, Django REST Framework 3.18.0, and FastAPI
0.141.1.

The unattended pass@1 run was executed from
`<repo>/tasks/drf-fastapi/drf-fastapi-007/source`:

```bash
sanka scan . --artifact-dir <local-path> --json --no-color
sanka plan . --to fastapi --strategy native --generation minimal \
  --package-manager uv --output <local-path> --artifact-dir <local-path> \
  --json --no-color
sanka apply --root . --artifact-dir <local-path> --output <local-path> \
  --plan-hash sha256:824978024173fd6cd3e24ad9835e6dbc112a06698dcc29fc4821f38c3c4f047a --bench-candidate <local-path> \
  --json --no-color
```

Scan reported 14 endpoints and scan hash `sha256:7b04951021c4e4d48991368d4355af8a6240f2f66c881a7f68df6273ea8cd1af`. The
native plan hash is `sha256:824978024173fd6cd3e24ad9835e6dbc112a06698dcc29fc4821f38c3c4f047a` with readiness
14.29%: 1 of 7
non-alias routes generatable and 6 requiring adaptation.
Adaptation codes: `SANKA_DRF_VIEWSET_OVERRIDES_UNSUPPORTED`.

The raw engine artifact is preserved locally with digest `sha256:df4a0e311239d6435aeb3691c01535f8e13fc7a52803e6123a91de870d2f82bb`. The
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
database, side-effect, route, and native-serving comparisons are 0/30.
