# Sanka compatibility-bridge baseline provenance (drf-fastapi-006)

Generated with the shipped engine — PyPI `sanka-cli` 0.1.8 delegating to
`sanka-migrate` 0.1.0a8 — installed into the fixture virtualenv
(`python 3.12.13`, `django 5.2.17`, `djangorestframework 3.18.0`,
`fastapi 0.141.1`) and run against the `drf-fastapi-006` fixture with:

```bash
sanka scan .
sanka plan . --to fastapi --strategy compatibility
sanka apply --root . --to fastapi --bench-candidate <dir>
```

Scan reported 14 endpoints, 1 serializer, 1 model, and 1 permission. The
compatibility plan covered all 14 endpoints at 100% bridge readiness (plan
hash `sha256:c0a4bee18baf88101a0771c13a537bede06cc622fd79b6ec93246e231f2a1503`).
The `--bench-candidate` flag was refused for this plan — the engine prints
`error: benchmark candidates require a native plan; run sanka plan --to
fastapi` — while still generating the bridge into `.sanka/output/fastapi/`.

Packaged like the earlier bridge baselines: the generated `sanka_compat.py`
runtime was saved as the fixed `target_app.py` entrypoint with
`app = create_app()` appended, and manifest `source_root` set to `.`. No
request-dispatch logic was changed. The bridge preserves all 32 behavior and
database comparisons, including nested constraint rollback, while failing the
anti-proxy native-target gate on recorded serving evidence.
