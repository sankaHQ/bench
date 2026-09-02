# Sanka compatibility-bridge provenance (drf-fastapi-007)

Generated with PyPI `sanka-cli` 0.1.8 delegating to `sanka-migrate`
0.1.0a8, installed inside the fixture virtualenv with Python 3.12.13,
Django 5.2.17, Django REST Framework 3.18.0, and FastAPI 0.141.1.

The engine was run from `<repo>/tasks/drf-fastapi/drf-fastapi-007/source`:

```bash
sanka scan .
sanka plan . --to fastapi --strategy compatibility
sanka apply --root . --to fastapi
```

Scan reported 14 endpoints and scan hash
`sha256:271c8c10f125fb202d7c3b875478ee3ce211450692692d55202276151a5ded0e`.
The compatibility plan reported 100% bridge readiness with plan hash
`sha256:05545c810ff6489dd86730d5c5827576bcc2bc45715dc12599b9dad979876494`.

The CLI refuses `--bench-candidate` for compatibility plans. Following the
benchmark's established 003/004 packaging convention, the generated
`sanka_compat.py` was frozen as `overlay/target_app.py`, the generated manifest
was copied beside it with `source_root` rebased to the evaluator overlay, and
`app = create_app()` was exposed as the candidate entrypoint. No route or
request behavior was changed.
