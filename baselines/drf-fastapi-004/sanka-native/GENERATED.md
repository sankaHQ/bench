# Sanka native-converter provenance (drf-fastapi-004)

Generated once with published PyPI `sanka-cli` 0.1.8 delegating to
`sanka-migrate` 0.1.0a10, installed inside the fixture-capable virtualenv with
Python 3.12.13, Django 5.2.17, Django REST Framework 3.18.0, and FastAPI
0.141.1.

The unattended pass@1 run was executed from
`<repo>/tasks/drf-fastapi/drf-fastapi-004/source`:

```bash
sanka scan . --artifact-dir <local-path> --json --no-color
sanka plan . --to fastapi --strategy native --generation minimal \
  --package-manager uv --output <local-path> --artifact-dir <local-path> \
  --json --no-color
sanka apply --root . --artifact-dir <local-path> --output <local-path> \
  --plan-hash sha256:cecb1753b48ca78ac67828a2a1316b04c956a10938a1d88a172aff0f6e1e099c --bench-candidate <local-path> \
  --json --no-color
```

Scan reported 26 endpoints and scan hash `sha256:9d5c71ab9d78a7f738dfa040005eb465e2c36b7662277cbd684bac3f6c954bf1`. The
native plan hash is `sha256:cecb1753b48ca78ac67828a2a1316b04c956a10938a1d88a172aff0f6e1e099c` with readiness
53.85%: 7 of 13
non-alias routes generatable and 6 requiring adaptation.
Adaptation codes: `SANKA_DRF_CUSTOM_ACTION_UNSUPPORTED`, `SANKA_DRF_VIEWSET_KIND_UNSUPPORTED`.

The raw engine artifact is preserved locally with digest `sha256:56ddcf81e85a8fd97417dd7b03caab641e2da37fbe81437a6f52a35cffe38614`. The
committed copy changes only machine-local absolute path strings to `<repo>` or
`<local-path>`; generated application code and behavioral content are otherwise
untouched.

## Honest outcome: candidate generated

The default 50% readiness gate allowed apply to proceed. The engine emitted the
overlay, candidate descriptor, reviewed plan, structured gap report, and
structural verification report in one attempt. Apply reported migration state
`generated_not_verified`. Nothing was retried or hand-fixed.

## Evaluator outcome

Local and network-disabled Docker evaluation have identical gates and metrics.
The candidate fails honestly at 5/17 behavior and 10/17 database parity while
passing 17/17 side-effect, route, and native-serving comparisons. The explicit
501 adaptation stubs are native FastAPI routes, but do not earn behavioral
credit.
