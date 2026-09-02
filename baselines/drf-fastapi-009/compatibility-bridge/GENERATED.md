# Sanka compatibility-bridge provenance (drf-fastapi-009)

Generated with PyPI `sanka-cli` 0.1.8 delegating to `sanka-migrate`
0.1.0a8, installed inside the fixture virtualenv with Python 3.12.13,
Django 5.2.17, Django REST Framework 3.18.0, and FastAPI 0.141.1.

The engine was run from `<repo>/tasks/drf-fastapi/drf-fastapi-009/source`:

```bash
sanka scan .
sanka plan . --to fastapi --strategy compatibility
sanka apply --root . --to fastapi
```

Scan reported 12 endpoints and scan hash
`sha256:2c9527862aeb49ca669da9a697ddc07de672de01a475ae9006444429f41bacc0`.
The compatibility plan emitted all 12 routes at 100% bridge readiness with
plan hash `sha256:1ebd5fcf390865063aee2b9456ae710a1db3130585d4278baadeffe3102dd2b9`.

The CLI refuses `--bench-candidate` for compatibility plans. Following the
benchmark's established 003/004 packaging convention, the generated
`sanka_compat.py` was frozen as `overlay/target_app.py`, the generated manifest
was copied beside it with `source_root` rebased to the evaluator overlay, and
`app = create_app()` was exposed as the candidate entrypoint. No route or
request behavior was changed.
