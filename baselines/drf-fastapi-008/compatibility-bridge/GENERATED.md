# Sanka compatibility-bridge provenance (drf-fastapi-008)

Generated with PyPI `sanka-cli` 0.1.8 delegating to `sanka-migrate`
0.1.0a8, installed inside the fixture virtualenv with Python 3.12.13,
Django 5.2.17, Django REST Framework 3.18.0, and FastAPI 0.141.1.

The engine was run from `<repo>/tasks/drf-fastapi/drf-fastapi-008/source`:

```bash
sanka scan .
sanka plan . --to fastapi --strategy compatibility
sanka apply --root . --to fastapi
```

Scan reported 36 endpoints and scan hash
`sha256:69a673430c0d2cfb8f0e40337fb53dc5b1909dce08cff6d82177f84db6aba7d9`.
The compatibility plan emitted 32 routes at 89% bridge readiness with plan
hash `sha256:9a8c31269d92285e96798725b3044318d81e12fe93e047135d1296977a7343bf`.
The four dynamic-regex methods were identified for manual adaptation and are
outside the graded request set; the source fixture still regression-tests the
dynamic route itself.

The CLI refuses `--bench-candidate` for compatibility plans. Following the
benchmark's established 003/004 packaging convention, the generated
`sanka_compat.py` was frozen as `overlay/target_app.py`, the generated manifest
was copied beside it with `source_root` rebased to the evaluator overlay, and
`app = create_app()` was exposed as the candidate entrypoint. No route or
request behavior was changed.
