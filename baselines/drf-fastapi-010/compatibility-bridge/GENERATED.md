# Sanka compatibility-bridge provenance (drf-fastapi-010)

Generated with PyPI `sanka-cli` 0.1.8 delegating to `sanka-migrate`
0.1.0a8, installed inside the fixture virtualenv with Python 3.12.13,
Django 5.2.17, Django REST Framework 3.18.0, and FastAPI 0.141.1.

The engine was run from `<repo>/tasks/drf-fastapi/drf-fastapi-010/source`:

```bash
sanka scan .
sanka plan . --to fastapi --strategy compatibility
sanka apply --root . --to fastapi
```

Scan reported 5 endpoints and scan hash
`sha256:1a04fdc293f968e80e2cb01db14c90f7bd74215f392e168606bd62942f869e53`.
The compatibility plan emitted all 5 routes at 100% bridge readiness with
plan hash `sha256:7dcecd1f2bb070759b595bb8a1ffb53e92608ee1d9710bc390a603980b42c2d2`.

The CLI refuses `--bench-candidate` for compatibility plans. Following the
benchmark's established 003/004 packaging convention, the generated
`sanka_compat.py` was frozen as `overlay/target_app.py`, the generated manifest
was copied beside it with `source_root` rebased to the evaluator overlay, and
`app = create_app()` was exposed as the candidate entrypoint. No route or
request behavior was changed.
