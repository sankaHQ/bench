# Sanka native-converter provenance (drf-fastapi-008)

Generated once with published PyPI `sanka-cli` 0.1.8 delegating to
`sanka-migrate` 0.1.0a10, installed inside the fixture-capable virtualenv with
Python 3.12.13, Django 5.2.17, Django REST Framework 3.18.0, and FastAPI
0.141.1.

The unattended pass@1 run was executed from
`<repo>/tasks/drf-fastapi/drf-fastapi-008/source`:

```bash
sanka scan . --artifact-dir <local-path> --json --no-color
sanka plan . --to fastapi --strategy native --generation minimal \
  --package-manager uv --output <local-path> --artifact-dir <local-path> \
  --json --no-color
sanka apply --root . --artifact-dir <local-path> --output <local-path> \
  --plan-hash sha256:e3623b585c2cd50368fe87543d0ad3718fa6745c20d6a07766dab99e14870c7d --bench-candidate <local-path> \
  --json --no-color
```

Scan reported 36 endpoints and scan hash `sha256:8fcfb1f0ae49ad26b14965b2f26bf888ab20439a6e73639dc6652716a4603d59`. The
native plan hash is `sha256:e3623b585c2cd50368fe87543d0ad3718fa6745c20d6a07766dab99e14870c7d` with readiness
24.14%: 7 of 29
non-alias routes generatable and 22 requiring adaptation.
Adaptation codes: `SANKA_DRF_VIEW_KIND_UNSUPPORTED`.

The raw engine artifact is preserved locally with digest `sha256:3abc7e0bdb2ae1f9dfdbf28d3a557c751f4035159f018e3ffca50bc56a66021a`. The
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
database, side-effect, route, and native-serving comparisons are 0/32.
