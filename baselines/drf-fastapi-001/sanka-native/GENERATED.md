# Sanka native-converter provenance (drf-fastapi-001)

Generated once with published PyPI `sanka-cli` 0.1.8 delegating to
`sanka-migrate` 0.1.0a10, installed inside the fixture-capable virtualenv with
Python 3.12.13, Django 5.2.17, Django REST Framework 3.18.0, and FastAPI
0.141.1.

The unattended pass@1 run was executed from
`<repo>/tasks/drf-fastapi/drf-fastapi-001/source`:

```bash
sanka scan . --artifact-dir <local-path> --json --no-color
sanka plan . --to fastapi --strategy native --generation minimal \
  --package-manager uv --output <local-path> --artifact-dir <local-path> \
  --json --no-color
sanka apply --root . --artifact-dir <local-path> --output <local-path> \
  --plan-hash sha256:b75bfdde7be13b8c9a05865be37b61058d9ec17dcf3ffe2a1e37060a192fe894 --bench-candidate <local-path> \
  --json --no-color
```

Scan reported 14 endpoints and scan hash `sha256:41a1bd39dc6cd03d40602be8eb7b8f469fba8ccbaa67179446e9aaae826ef98a`. The
native plan hash is `sha256:b75bfdde7be13b8c9a05865be37b61058d9ec17dcf3ffe2a1e37060a192fe894` with readiness
100%: 7 of 7
non-alias routes generatable and 0 requiring adaptation.
Adaptation codes: none.

The raw engine artifact is preserved locally with digest `sha256:68a946253e4df0a5e8574495eca4b28d2d9898bfc751ba99653a77c36f3f18d7`. The
committed copy changes only machine-local absolute path strings to `<repo>` or
`<local-path>`; generated application code and behavioral content are otherwise
untouched.

## Honest outcome: candidate generated

The default 50% readiness gate allowed apply to proceed. The engine emitted the
overlay, candidate descriptor, reviewed plan, structured gap report, and
structural verification report in one attempt. Apply reported migration state
`generated_not_verified`. Nothing was retried or hand-fixed.

## Evaluator outcome

Local and network-disabled Docker evaluation both pass every hard gate: 5/5
behavior, database, side-effect, route, and native-serving comparisons.
