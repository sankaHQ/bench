# Sanka native-converter provenance (drf-fastapi-003)

Generated once with published PyPI `sanka-cli` 0.1.8 delegating to
`sanka-migrate` 0.1.0a10, installed inside the fixture-capable virtualenv with
Python 3.12.13, Django 5.2.17, Django REST Framework 3.18.0, and FastAPI
0.141.1.

The unattended pass@1 run was executed from
`<repo>/tasks/drf-fastapi/drf-fastapi-003/source`:

```bash
sanka scan . --artifact-dir <local-path> --json --no-color
sanka plan . --to fastapi --strategy native --generation minimal \
  --package-manager uv --output <local-path> --artifact-dir <local-path> \
  --json --no-color
sanka apply --root . --artifact-dir <local-path> --output <local-path> \
  --plan-hash sha256:221a3d35b244b7358349ac831bce73d28222aa00265da2cff301e4d0da727465 --bench-candidate <local-path> \
  --json --no-color
```

Scan reported 14 endpoints and scan hash `sha256:9841422a5cf2a0190404fb8dfa072d400e5c130e1bebf4d4300611a4b89cec9d`. The
native plan hash is `sha256:221a3d35b244b7358349ac831bce73d28222aa00265da2cff301e4d0da727465` with readiness
100%: 7 of 7
non-alias routes generatable and 0 requiring adaptation.
Adaptation codes: none.

The raw engine artifact is preserved locally with digest `sha256:3111e1b50f19fe45c8e917b6b6c303951b44c177966aaaf72309d6559a704f7f`. The
committed copy changes only machine-local absolute path strings to `<repo>` or
`<local-path>`; generated application code and behavioral content are otherwise
untouched.

## Honest outcome: candidate generated

The default 50% readiness gate allowed apply to proceed. The engine emitted the
overlay, candidate descriptor, reviewed plan, structured gap report, and
structural verification report in one attempt. Apply reported migration state
`generated_not_verified`. Nothing was retried or hand-fixed.

## Evaluator outcome

Local and network-disabled Docker evaluation both pass every hard gate: 16/16
behavior, database, side-effect, route, and native-serving comparisons.
