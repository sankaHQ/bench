# Sanka compatibility-bridge provenance (drf-fastapi-011)

Generated with PyPI `sanka-cli` 0.1.8 delegating to `sanka-migrate`
0.1.0a8, installed inside the fixture virtualenv with Python 3.12.13,
Django 5.2.17, Django REST Framework 3.18.0, and FastAPI 0.141.1.

The engine was run from `<repo>/tasks/drf-fastapi/drf-fastapi-011/source`:

```bash
sanka scan .
sanka plan . --to fastapi --strategy compatibility
sanka apply --root . --to fastapi
```

Scan reported 5 endpoints and scan hash
`sha256:67733c4559dc8fce8d14d94914932d84c712841c0335acf02fa742ff7f289a10`.
The compatibility plan emitted all 5 routes at 100% bridge readiness with
plan hash `sha256:0e1b86664ac50a20d1b95b2b2068c62bbb38c8a9914a38b9fa383dfe0871dd3c`.

The CLI refuses `--bench-candidate` for compatibility plans. Following the
benchmark's established 003/004 packaging convention, the generated
`sanka_compat.py` was frozen as `overlay/target_app.py`, the generated manifest
was copied beside it with `source_root` rebased to the evaluator overlay, and
`app = create_app()` was exposed as the candidate entrypoint. No route or
request behavior was changed.
