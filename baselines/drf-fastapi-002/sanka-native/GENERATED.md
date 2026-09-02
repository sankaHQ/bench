# Sanka native-converter provenance (drf-fastapi-002)

Generated once with published PyPI `sanka-cli` 0.1.8 delegating to
`sanka-migrate` 0.1.0a10, installed inside the fixture-capable virtualenv with
Python 3.12.13, Django 5.2.17, Django REST Framework 3.18.0, and FastAPI
0.141.1.

The unattended pass@1 run was executed from
`<repo>/tasks/drf-fastapi/drf-fastapi-002/source`:

```bash
sanka scan . --artifact-dir <local-path> --json --no-color
sanka plan . --to fastapi --strategy native --generation minimal \
  --package-manager uv --output <local-path> --artifact-dir <local-path> \
  --json --no-color
sanka apply --root . --artifact-dir <local-path> --output <local-path> \
  --plan-hash sha256:ed2fe4fa0b6384b7e17737a2adf145440c949f60423e4a203b04bcfe6a87c9a7 --bench-candidate <local-path> \
  --json --no-color
```

Scan reported 14 endpoints and scan hash `sha256:6a2cc18c229b6123713f7d84a1c7d75bdfa07e247c65f694f06ee9615cddb6a7`. The
native plan hash is `sha256:ed2fe4fa0b6384b7e17737a2adf145440c949f60423e4a203b04bcfe6a87c9a7` with readiness
100%: 7 of 7
non-alias routes generatable and 0 requiring adaptation.
Adaptation codes: none.

The raw engine artifact is preserved locally with digest `sha256:39484880e3903c170062dcae0c2b1dd2e12ffeea2c00b439a6b8b3088b3c42b1`. The
committed copy changes only machine-local absolute path strings to `<repo>` or
`<local-path>`; generated application code and behavioral content are otherwise
untouched.

## Honest outcome: candidate generated

The default 50% readiness gate allowed apply to proceed. The engine emitted the
overlay, candidate descriptor, reviewed plan, structured gap report, and
structural verification report in one attempt. Apply reported migration state
`generated_not_verified`. Nothing was retried or hand-fixed.

## Evaluator outcome

Local and network-disabled Docker evaluation both pass every hard gate: 13/13
behavior, database, side-effect, route, and native-serving comparisons.
