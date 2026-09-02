# Sanka compatibility-bridge baseline provenance (drf-fastapi-004)

Generated with the shipped engine — PyPI `sanka-cli` 0.1.8 delegating to
`sanka-migrate` 0.1.0a8 — installed into the fixture virtualenv
(`django 5.2.17`, `djangorestframework 3.18.0`, `fastapi 0.141.1`) and run
against the `drf-fastapi-004` fixture with:

```bash
sanka scan .
sanka plan . --to fastapi --strategy compatibility
sanka apply --root . --to fastapi --bench-candidate <dir>
```

Scan reported 26 endpoints, 3 serializers, 3 models, and 1 custom action;
the compatibility plan covered all 26 endpoints at 100% bridge readiness
(plan hash `sha256:983990b96807f9ef751706eb9e36c0271c7a80431621186cfa1f2e16956b654a`).
The `--bench-candidate` flag was refused for this plan — the engine prints
`error: benchmark candidates require a native plan; run sanka plan --to
fastapi` — while still generating the bridge into `.sanka/output/fastapi/`.

Packaged like the other bridge baselines: the generated `sanka_compat.py`
runtime saved as the fixed `target_app.py` entrypoint with
`app = create_app()` appended, and manifest `source_root` set to `.`.
No request-dispatch logic was changed. The bridge proxies every request —
signals included — through the in-process Django ASGI application, so it
preserves behavior and the audit trail while failing the anti-proxy
native-target gate on recorded serving evidence.
