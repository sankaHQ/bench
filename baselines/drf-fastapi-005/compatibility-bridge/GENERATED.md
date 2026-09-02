# Sanka compatibility-bridge baseline provenance (drf-fastapi-005)

Generated with the shipped engine — PyPI `sanka-cli` 0.1.8 delegating to
`sanka-migrate` 0.1.0a8 — installed into the fixture virtualenv
(`django 5.2.17`, `djangorestframework 3.18.0`, `fastapi 0.141.1`) and run
against the `drf-fastapi-005` fixture with:

```bash
sanka scan .
sanka plan . --to fastapi --strategy compatibility
sanka apply --root . --to fastapi --bench-candidate <dir>
```

Scan reported 16 endpoints, 1 serializer, 1 model, 1 permission, and 1
custom action. The compatibility plan covered all 16 endpoints at 100%
bridge readiness (plan hash
`sha256:b73a57af8f1f93bf205f53b81bb34ee929e8aaddf2f9c05e3d77de0120c47818`).
The `--bench-candidate` flag was refused for this plan — the engine prints
`error: benchmark candidates require a native plan; run sanka plan --to
fastapi` — while still generating the bridge into
`.sanka/output/fastapi/`.

Packaged like the earlier bridge baselines: the generated `sanka_compat.py`
runtime saved as the fixed `target_app.py` entrypoint with
`app = create_app()` appended, and manifest `source_root` set to `.`. No
request-dispatch logic was changed. The bridge proxies token and session
authentication, CSRF checks, action permissions, and object permissions
through the in-process Django ASGI application, so it preserves behavior
while failing the anti-proxy native-target gate on recorded serving evidence.
